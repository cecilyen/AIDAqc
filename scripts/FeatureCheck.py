import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import nibabel as nib
from nilearn.plotting import plot_img
from nilearn.image import index_img
import alive_progress as ap

import pv_conv2Nifti as pr
import pv_parser as par
from file_naming import FEATURE_FILE_TEMPLATE, iter_address_files, sequence_type_from_name
from QC import (
    ResCalculator, GhostCheck, snr_calculator_chang,
    snr_calculator_normal, tsnr_calculator, Ismotion
)


METRIC_COLUMNS = {
    'anat': ['SNR Chang', 'SNR Normal'],
    'diff': ['SNR Chang', 'SNR Normal', 'Displacement factor (std of Mutual information)'],
    'func': ['tSNR (Averaged Brain ROI)', 'Displacement factor (std of Mutual information)'],
}


def output_columns(seq_type: str, include_sequence_name: bool) -> List[str]:
    """Return the CSV column order for one sequence type."""
    metadata = ['FileAddress']
    if include_sequence_name:
        metadata.append('sequence name')
    metadata.extend(['corresponding_img', 'SpatRx', 'SpatRy', 'SpatRz', 'Ghosting'])
    return metadata + METRIC_COLUMNS[seq_type]


def load_address_files(path: str) -> Dict[str, pd.DataFrame]:
    """Load address CSV files and return dictionary by sequence type."""
    address_book = {}
    
    for file_path in iter_address_files(path):
        seq_type = sequence_type_from_name(file_path.name)
        if seq_type and seq_type not in address_book:
            address_book[seq_type] = pd.read_csv(file_path)
    
    return address_book


def create_inspection_image(input_file: nib.Nifti1Image, 
                           save_path: str, 
                           img_name: str) -> None:
    """Create and save orthogonal view of image for manual inspection."""
    if len(input_file.shape) == 4:
        display_img = index_img(input_file, 0)
    else:
        display_img = input_file
    
    plot_img(display_img, title=img_name, output_file=save_path)


def calculate_common_features(input_file: nib.Nifti1Image) -> Tuple[np.ndarray, float]:
    """Calculate features common to all sequence types."""
    spatial_res = ResCalculator(input_file)
    ghosting = GhostCheck(input_file)
    return spatial_res, ghosting


def calculate_snr_features(input_file: nib.Nifti1Image) -> Tuple[float, float]:
    """Calculate SNR features for anatomical and diffusion sequences."""
    snr_chang = snr_calculator_chang(input_file)
    snr_normal = snr_calculator_normal(input_file)
    return snr_chang, snr_normal


def calculate_motion_displacement(input_file: nib.Nifti1Image) -> float:
    """Return the motion displacement metric written to feature CSVs."""
    return Ismotion(input_file)[3]


def load_raw_bruker_data(file_path: str) -> Tuple[Optional[nib.Nifti1Image], Optional[str]]:
    """Load raw Bruker data and return NIfTI image and sequence key."""
    path_parts = Path(file_path).parts
    
    procno = '1'
    expno = path_parts[-1]
    study = path_parts[-2]
    raw_folder = os.sep.join(path_parts[:-2])
    proc_folder = os.path.join(raw_folder, 'proc_data')
    
    # Check for required parameter files
    visu_pars = os.path.join(file_path, 'pdata', '1', 'visu_pars')
    acqp_path = os.path.join(file_path, 'acqp')
    
    if not (os.path.isfile(visu_pars) and os.path.isfile(acqp_path)):
        raise FileNotFoundError("Missing visu_pars or acqp file")
    
    # Load Bruker data
    pv = pr.Bruker2Nifti(study, expno, procno, raw_folder, proc_folder, ftype='NIFTI_GZ')
    pv.read_2dseq(map_raw=False, pv6=False)
    input_file = nib.squeeze_image(pv.nim)
    
    # Create proper affine matrix for nilearn
    affine = np.eye(4)
    pixdim = pv.nim.header.get('pixdim')
    for i in range(4):
        affine[i, i] = pixdim[i + 1]
    
    input_file = nib.Nifti1Image(input_file.get_fdata(), affine=affine, dtype=np.int32)
    
    # Get sequence information
    scan_info = par.read_param_file(acqp_path)
    method_name = scan_info[1]["ACQ_method"].upper()
    scan_name = scan_info[1]["ACQ_scan_name"].upper()
    sequence_key = method_name + scan_name
    
    return input_file, sequence_key


def process_single_file(file_path: str, 
                       seq_type: str, 
                       output_path: str,
                       file_index: int,
                       is_raw: bool = False) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    """
    Process a single file and extract features.
    
    Returns:
        Tuple of (feature_dict, error_message)
    """
    try:
        # Load data
        if is_raw:
            input_file, sequence_key = load_raw_bruker_data(file_path)
        else:
            input_file = nib.load(file_path)
            sequence_key = None
        
        # Create inspection image
        qc_path = os.path.join(output_path, "manual_slice_inspection")
        os.makedirs(qc_path, exist_ok=True)
        
        path_obj = Path(file_path)
        if is_raw:
            img_name = path_obj.parts[-2]
        else:
            img_name = f"{path_obj.parts[-2]}_{path_obj.name}"
        
        full_img_name = f"{seq_type}_{img_name}_{file_index}.png"
        full_img_name = full_img_name.replace('.nii', '').replace('.gz', '')
        
        svg_path = os.path.join(qc_path, full_img_name)
        create_inspection_image(input_file, svg_path, full_img_name)
        
        # Calculate common features
        spatial_res, ghosting = calculate_common_features(input_file)
        
        row = {
            'FileAddress': file_path,
            'corresponding_img': full_img_name,
            'SpatRx': spatial_res[0],
            'SpatRy': spatial_res[1],
            'SpatRz': spatial_res[2],
            'Ghosting': ghosting,
        }
        if sequence_key:
            row['sequence name'] = sequence_key
        
        # Calculate sequence-specific features
        if seq_type == 'anat':
            snr_chang, snr_normal = calculate_snr_features(input_file)
            row['SNR Chang'] = snr_chang
            row['SNR Normal'] = snr_normal
            
        elif seq_type == 'diff':
            snr_chang, snr_normal = calculate_snr_features(input_file)
            row['SNR Chang'] = snr_chang
            row['SNR Normal'] = snr_normal
            row['Displacement factor (std of Mutual information)'] = calculate_motion_displacement(input_file)
            
        elif seq_type == 'func':
            tsnr = tsnr_calculator(input_file)
            row['tSNR (Averaged Brain ROI)'] = tsnr
            row['Displacement factor (std of Mutual information)'] = calculate_motion_displacement(input_file)
        
        return row, None
        
    except (ValueError, SystemError, KeyError, FileNotFoundError, 
            nib.loadsave.ImageFileError) as e:
        error_msg = f"{file_path}_{type(e).__name__}"
        print(f"{type(e).__name__}: {file_path}")
        return None, error_msg


def process_sequence_type(seq_type: str, 
                          file_list: List[str], 
                          output_path: str,
                          is_raw: bool = False) -> Tuple[List[Dict[str, object]], List[str]]:
    """Process all files of a given sequence type."""
    print(f'{seq_type} processing...\n')
    
    rows = []
    error_list = []
    
    with ap.alive_bar(len(file_list), spinner='wait') as bar:
        for idx, file_path in enumerate(file_list, start=1):
            row, error = process_single_file(
                str(file_path), seq_type, output_path, idx, is_raw
            )
            
            if error:
                error_list.append(error)
            elif row:
                rows.append(row)
            
            bar()
    
    return rows, error_list


def save_results(rows: List[Dict[str, object]],
                seq_type: str, 
                output_path: str) -> None:
    """Save feature rows to a CSV file."""
    include_sequence_name = any('sequence name' in row for row in rows)
    df = pd.DataFrame(rows, columns=output_columns(seq_type, include_sequence_name))
    output_file = os.path.join(
        output_path,
        FEATURE_FILE_TEMPLATE.format(seq_type=seq_type),
    )
    df.to_csv(output_file, index=False)


def process_features(path: str, is_raw: bool = False) -> None:
    """
    Main function to process features for all sequence types.
    
    Args:
        path: Path to the directory containing address CSV files
        is_raw: Whether processing raw Bruker data (True) or NIfTI (False)
    """
    # Load address files
    address_book = load_address_files(path)
    
    if not address_book:
        print("No address files found!")
        return
    
    all_errors = []
    
    # Process each sequence type
    for seq_type, addresses_df in address_book.items():
        if addresses_df.empty:
            continue
        
        file_list = addresses_df.iloc[:, 0].tolist()
        
        # Process files
        rows, errors = process_sequence_type(
            seq_type, file_list, path, is_raw
        )
        
        # Save results
        if rows:
            save_results(rows, seq_type, path)
        
        all_errors.extend(errors)
        
        if errors:
            print(f'{len(errors)} faulty file(s) found for {seq_type}\n')
    
    # Save error list
    if all_errors:
        df_errors = pd.DataFrame({'ErrorData': all_errors})
        error_file = os.path.join(path, "CanNotProcessTheseFiles.csv")
        df_errors.to_csv(error_file, index=False)
        print(f"Error list saved to: {error_file}")
    
    print(f'\n\nOutput files created: {path}')
    print('\n\n%%%%%%%%%%%%% END OF STAGE 2 %%%%%%%%%%%%%%%\n\n')


def CheckingRawFeatures(path: str) -> None:
    """Process raw Bruker format features."""
    process_features(path, is_raw=True)


def CheckingNiftiFeatures(path: str) -> None:
    """Process NIfTI format features."""
    process_features(path, is_raw=False)

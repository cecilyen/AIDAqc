"""
Created on 10/08/2017

@author: Niklas Pallast
Neuroimaging & Neuroengineering
Department of Neurology
University Hospital Cologne



"""

import os
import sys
from pathlib import Path

import numpy as np
import nibabel as nib
import nibabel.nifti1 as nii
import pv_parseBruker_md_np as pB
import P2_IDLt2_mapping as mapT2


OUTPUT_EXTENSIONS = {
    "NIFTI_GZ": "nii.gz",
    "NIFTI": "nii",
    "ANALYZE": "img",
}


class Bruker2Nifti:
    def __init__(self, study, expno, procno, rawfolder, procfolder, ftype='NIFTI_GZ'):
        self.study = study
        self.expno = str(expno)
        self.procno = str(procno)
        self.rawfolder = rawfolder
        self.procfolder = procfolder
        self.ftype = ftype

    def read_2dseq(self, map_raw=False, pv6=False, sc=1.0):
        study = self.study
        expno = self.expno
        procno = self.procno
        rawfolder = self.rawfolder

        self.acqp = pB.parsePV(os.path.join(rawfolder, study, expno, 'acqp'))
        self.method = pB.parsePV(os.path.join(rawfolder, study, expno, 'method'))
        self.subject = pB.parsePV(os.path.join(rawfolder, study, 'subject'))
        # get header information
        datadir = os.path.join(rawfolder, study, expno, 'pdata', procno)
        #self.d3proc = pB.parsePV(os.path.join(datadir, 'd3proc'))   # removed for PV6
        self.visu_pars = pB.parsePV(os.path.join(datadir, 'visu_pars'))
        hdr = pB.getNiftiHeader(self.visu_pars, sc=sc)
        #print("hdr:", hdr)

        if hdr is None or not isinstance(hdr[12], str):
            raise ValueError("Unable to determine the NIfTI header for this scan")

        # read '2dseq' file
        with open(os.path.join(datadir, '2dseq'), 'rb') as f_id:
            data = np.fromfile(f_id, dtype=np.dtype(hdr[12])).reshape(
                hdr[1], hdr[2], hdr[3], hdr[4], order='F'
            )

        # map to raw data range (PV6)
        if map_raw:
            visu_core_data_slope = np.array(map(float, self.visu_pars['VisuCoreDataSlope'].split()), dtype=np.float32)
            visu_core_data_offs = np.array(map(float, self.visu_pars['VisuCoreDataOffs'].split()), dtype=np.float32)
            visu_core_data_shape = list(data.shape)
            visu_core_data_shape[:2] = (1, 1)
            if pv6:
                data = data / visu_core_data_slope.reshape(visu_core_data_shape)
            else:
                data = data * visu_core_data_slope.reshape(visu_core_data_shape)
            data = data + visu_core_data_offs.reshape(visu_core_data_shape)

        # NIfTI image
        #data = np.flip(data, axis=(1,2))  #flip z-axis 
        nim = nii.Nifti1Image(data, None)

        # NIfTI header
        header = nim.header
        header['pixdim'] = [0.0, hdr[5], hdr[6], hdr[7], hdr[8], 0.0, 0.0, 0.0]
        #nim.setXYZUnit('mm')
        header.set_xyzt_units(xyz='mm', t=None)
        #nim.header = header
        #header = nim.get_header()
        #print("header:"); print(header)

        # write header in xml structure
        #xml = pB.getXML(datadir + "/")
        xml = pB.getXML(os.path.join(datadir, 'visu_pars'))
        #print("xml:"); print(xml)

        # add protocol information (method, acqp, visu_pars, d3proc) to Nifti's header extensions
        #nim.extensions += ('comment', xml)
        #extension = nii.Nifti1Extension('comment', xml)

        self.hdr = hdr
        self.nim = nim
        self.xml = xml

    def save_nifti(self, subfolder=''):
        if not hasattr(self, 'nim'):
            return

        protocol = self.acqp.get('ACQ_protocol_name', '')
        if "Localizer" in protocol:
            category = "Localizer"
        elif "DTI" in protocol or "Diffusion" in protocol:
            category = "DTI"
        elif "fMRI" in protocol:
            category = "fMRI"
        elif "Turbo" in protocol:
            category = "T2w"
        elif "MSME" in protocol:
            category = "T2map"
        else:
            category = "Others"

        procfolder = Path(self.procfolder) / self.study / category
        if subfolder:
            procfolder /= subfolder
        procfolder.mkdir(parents=True, exist_ok=True)

        ext = OUTPUT_EXTENSIONS.get(self.ftype, 'nii.gz')

        fname = '.'.join([self.study, self.expno, self.procno, ext])

        # write Nifti file

        output_path = procfolder / fname
        print(output_path)
        nib.save(self.nim, str(output_path))

        return str(output_path)

    def save_table(self, subfolder= ''):
        required = ('PVM_DwEffBval', 'PVM_DwAoImages', 'PVM_DwNDiffDir', 'PVM_DwDir')
        if not all(key in self.method for key in required):
            return

        procfolder = Path(self.procfolder) / self.study / subfolder
        procfolder.mkdir(parents=True, exist_ok=True)

        dw_eff_bval = np.fromstring(self.method['PVM_DwEffBval'], sep=' ', dtype=np.float32)
        dw_ao_images = int(self.method['PVM_DwAoImages'])
        dw_n_diff_dir = int(self.method['PVM_DwNDiffDir'])
        dw_dir = np.fromstring(self.method['PVM_DwDir'], sep=' ', dtype=np.float32)
        if dw_dir.size != dw_n_diff_dir * 3:
            raise ValueError("PVM_DwDir does not contain three values per direction")
        dw_dir = dw_dir.reshape((dw_n_diff_dir, 3))

        n_images = dw_ao_images + dw_n_diff_dir
        if dw_eff_bval.size < n_images:
            raise ValueError("PVM_DwEffBval does not contain all image b-values")

        bvals = np.zeros(n_images, dtype=np.float32)
        bvals[dw_ao_images:] = dw_eff_bval[dw_ao_images:n_images]
        bvecs = np.zeros((n_images, 3), dtype=np.float32)
        bvecs[dw_ao_images:] = dw_dir

        btable_path = procfolder / '.'.join([self.study, self.expno, self.procno, 'btable', 'txt'])
        bvals_path = procfolder / '.'.join([self.study, self.expno, self.procno, 'bvals', 'txt'])
        bvecs_path = procfolder / '.'.join([self.study, self.expno, self.procno, 'bvecs', 'txt'])

        for output_path in (btable_path, bvals_path, bvecs_path):
            print(output_path)
        np.savetxt(
            btable_path,
            np.column_stack((bvals, bvecs)),
            fmt=('%.4f', '%.8f', '%.8f', '%.8f'),
        )
        np.savetxt(bvals_path, bvals[np.newaxis, :], fmt='%.4f')
        np.savetxt(bvecs_path, bvecs.T, fmt='%.8f')
        return

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Convert ParaVision to NIfTI')

    requiredNamed = parser.add_argument_group('Required named arguments')
    requiredNamed.add_argument('-i', '--input_folder', required=True, help='raw data folder')
    # parser.add_argument('-o','--output_folder', help='output data folder')
    # parser.add_argument('study', help='study name')
    # parser.add_argument('expno', help='experiment number')
    # parser.add_argument('procno', help='processed (reconstructed) images number')
    parser.add_argument('-f','--model',
                        help='T2_2p  (default)  : Two   parameter T2 decay S(t) = S0 * exp(-t/T2)\n'
                             'T2_3p             : Three parameter T2 decay S(t) = S0 * exp(-t/T2) + C'
                        , nargs='?', const='T2_2p', type=str, default='T2_2p')
    parser.add_argument('-u','--upLim', help='upper limit of TE - default: 100', nargs='?', const=100, type=int, default=100)
    parser.add_argument('-s','--snrLim', help='upper limit of SNR - default: 1.5', nargs='?', const=1.5, type=float,
                        default=1.5)
    parser.add_argument('-k','--snrMethod', help='Brummer ,Chang, Sijbers', nargs='?', const='Brummer', type=str,
                        default='Brummer')
    parser.add_argument('-m', '--map_raw', action='store_true', help='get the real values')
    parser.add_argument('-p', '--pv6', action='store_true', help='ParaVision 6')
    parser.add_argument('-t', '--table', action='store_true', help='save b-values and diffusion directions')
    args = parser.parse_args()

    input_folder = Path(args.input_folder)
    if not input_folder.is_dir():
        sys.exit("Error: '%s' is not an existing directory." % (input_folder,))

    scan_names = [entry.name for entry in input_folder.iterdir() if entry.name.isdigit()]

    if not scan_names:
        sys.exit("Error: '%s' contains no numbered scans." % (input_folder,))

    print('Start to process ' + str(len(scan_names)) + ' scans...')
    procno = '1'
    study = input_folder.name
    print(study)
    img = None
    res_path = None
    for expno in sorted(scan_names, key=int):
        path = input_folder / expno / 'pdata' / procno
        if not path.is_dir():
            sys.exit("Error: '%s' is not an existing directory." % (path,))

        if (path / '2dseq').exists():

            img = Bruker2Nifti(
                study, expno, procno, str(input_folder.parent), str(input_folder),
                ftype='NIFTI_GZ'
            )
            img.read_2dseq(map_raw=args.map_raw, pv6=args.pv6)
            res_path = img.save_nifti()
            if res_path is None:
                continue

            if 'VisuAcqEchoTime' in img.visu_pars:

                echoTime = img.visu_pars['VisuAcqEchoTime']
                echoTime = np.fromstring(echoTime, dtype=float, sep=' ')
                if len(echoTime) > 3:
                    mapT2.getT2mapping(
                        res_path, args.model, args.upLim, args.snrLim,
                        args.snrMethod, echoTime
                    )
    if res_path is not None and img is not None:
        pathlog = Path(res_path).parent.parent / 'data.log'
        pathlog.write_text(img.subject['coilname'])

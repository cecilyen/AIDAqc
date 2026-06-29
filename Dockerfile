FROM continuumio/miniconda:latest

ENV PATH=/opt/conda/envs/aidaqc/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY aidaqc.yaml /tmp/aidaqc.yaml

SHELL ["/bin/bash", "-lc"]

RUN conda create -y -n aidaqc python=3.6 && \
    conda env update -n aidaqc --file /tmp/aidaqc.yaml && \
    conda clean -afy

RUN useradd -ms /bin/bash aida

COPY . /app
RUN chown -R aida:aida /app

USER aida

ENTRYPOINT ["conda", "run", "--no-capture-output", "-n", "aidaqc", "python", "/app/scripts/ParsingData.py"]

FROM continuumio/miniconda3:latest

WORKDIR /app

# Add conda to PATH
ENV PATH /opt/conda/bin:$PATH

# Create conda environment with pythonocc-core from conda-forge
RUN conda config --add channels conda-forge && \
    conda install -y \
    python=3.12 \
    pythonocc-core \
    postgresql \
    && conda clean -afy

# Install pip requirements (excluding pythonocc-core)
COPY requirements.txt .
RUN grep -v pythonocc-core requirements.txt > requirements_filtered.txt && \
    /opt/conda/bin/pip install --no-cache-dir -r requirements_filtered.txt

# Copy application code
COPY . .

# Create storage directories
RUN mkdir -p /app/storage/uploads /app/storage/gltf

# Create non-root user
RUN useradd -m -u 1000 plm && chown -R plm:plm /app
USER plm

# Expose port
EXPOSE 8000

# Run the application
CMD ["/opt/conda/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

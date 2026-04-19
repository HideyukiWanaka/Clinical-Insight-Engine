# =========================================================
# R Engine — Dockerized R + Plumber
# ★ Security: this image runs with NO internet connectivity
#   (enforced by docker-compose internal network)
# =========================================================

FROM r-base:4.3.2

# System dependencies for R packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libfontconfig1-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev \
    pkg-config \
    curl \
    libharfbuzz-dev \
    libfribidi-dev \
    cmake \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install R packages (all v1 required packages)
RUN Rscript -e "\
  install.packages(c( \
    'plumber', \
    'jsonlite', \
    'tidyverse', \
    'survival', \
    'survminer', \
    'finalfit', \
    'tableone', \
    'mice', \
    'zoo', \
    'pROC', \
    'forestplot', \
    'pwr', \
    'WebPower', \
    'powerSurvEpi', \
    'ggplot2', \
    'scales', \
    'logger' \
  ), repos='https://cloud.r-project.org', Ncpus=4L) \
"

COPY . .

EXPOSE 8001

# Plumber starts the API router which auto-scans skills/
CMD ["Rscript", "-e", "pr <- plumber::plumb('/app/plumber.R'); pr$run(host='0.0.0.0', port=8001)"]

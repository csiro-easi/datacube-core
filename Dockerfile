#FROM ubuntu:18.04
FROM csiroeasi/geo-python-base:latest

# Get the code, and put it in /code
ENV APPDIR=/tmp/code
RUN mkdir -p $APPDIR
COPY . $APPDIR
WORKDIR $APPDIR

# Set the locale, this is required for some of the Python packages
ENV LC_ALL C.UTF-8

# Install additional libraries useful or required for the python libraries used by ODC
# This mostly impacts python libraries that use additional c libraries during build to improve performance
# (e.g. pyrsistent, pyyaml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libyaml-dev libyaml-0-2 \
    && rm -rf /var/lib/apt/lists/*

# Install ODC
RUN python3 setup.py install

# Move docs and utils somewhere else, and remove the temp folder
RUN mkdir -p /opt/odc \
    && chmod +rwx /opt/odc \
    && mv $APPDIR/utils /opt/odc/ \
    && mv $APPDIR/docs /opt/odc/ \
    && mv $APPDIR/docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh \
    && rm -rf $APPDIR

# Fix an issue with libcurl...
RUN mkdir -p /etc/pki/tls/certs \
    && ln -s /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt;

# Set up an entrypoint that drops environment variables into the config file
ENTRYPOINT ["docker-entrypoint.sh"]

WORKDIR /opt/odc
CMD ["datacube","--help"]

FROM python

RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /pkgs/html2image
COPY . .

RUN $HOME/.local/bin/poetry install
RUN $HOME/.local/bin/poetry build
RUN pip install dist/*.whl

RUN apt-get update -y && apt-get install -y chromium


# CHROMIUM default flags for container environnement
# The --no-sandbox flag is needed by default since we execute chromium in a root environnement
RUN echo 'export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --no-sandbox"' >> /etc/chromium.d/default-flags

# MOTD
RUN echo " \n =============HTML2IMAGE============= \n Welcome to the html2image CLI container ! \n Type html2image -h for help :)" >> /etc/motd
RUN echo "clear" >> /root/.bashrc
RUN echo "cat /etc/motd" >> /root/.bashrc

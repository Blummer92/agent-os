FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# The upstream image currently carries a Yarn apt source whose signing key is
# unavailable during Codespaces feature installation. The official sshd feature
# runs apt-get update, so disable only that unused source before features run.
RUN rm -f /etc/apt/sources.list.d/yarn.list

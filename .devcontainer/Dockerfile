FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# The 2026-09-25 Codespaces creation log reproduces #1212: the inherited
# unused Yarn apt source has a missing signing key during sshd installation.
RUN rm -f /etc/apt/sources.list.d/yarn.list

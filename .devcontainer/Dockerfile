FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# #1212 proved the official sshd feature needs apt metadata refresh, while the
# inherited unused Yarn source can fail that refresh. Remove only that source;
# do not add replacement package trust or unrelated runtime dependencies.
RUN rm -f /etc/apt/sources.list.d/yarn.list

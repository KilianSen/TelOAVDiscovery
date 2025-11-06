FROM ubuntu:latest
LABEL authors="kilian"

ENTRYPOINT ["top", "-b"]
# A clean machine for the install test: systemd as PID 1 and one ordinary sudo account. The account
# stands for whoever installs the kit; the kit itself creates no user.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends systemd systemd-sysv dbus sudo git ca-certificates \
    && useradd -m -s /bin/bash someone \
    && echo 'someone ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/someone

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]

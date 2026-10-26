# Local TEST IMAP + ManageSieve server (Dovecot 2.3, the version of Ubuntu 24.04). Development and CI only.
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      dovecot-imapd dovecot-managesieved dovecot-sieve \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 5000 vmail && useradd -u 5000 -g vmail -d /srv/mail -s /usr/sbin/nologin vmail \
 && mkdir -p /srv/mail && chown vmail:vmail /srv/mail
COPY dovecot.conf /etc/dovecot/dovecot.conf
COPY users /etc/dovecot/users
EXPOSE 143 4190
CMD ["dovecot", "-F"]

# Local TEST IMAP + ManageSieve + LMTP + SMTP AUTH submission (GitHub #20).
# Development and CI only. :587 requires AUTH (smtp_auth_lmtp.py → LMTP).
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      dovecot-imapd dovecot-managesieved dovecot-sieve dovecot-lmtpd python3 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -g 5000 vmail && useradd -u 5000 -g vmail -d /srv/mail -s /usr/sbin/nologin vmail \
 && mkdir -p /srv/mail && chown vmail:vmail /srv/mail
COPY dovecot.conf /etc/dovecot/dovecot.conf
COPY users /etc/dovecot/users
COPY vacation-sendmail.sh /usr/local/bin/vacation-sendmail
COPY smtp_auth_lmtp.py /usr/local/bin/smtp_auth_lmtp.py
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/vacation-sendmail /usr/local/bin/smtp_auth_lmtp.py /usr/local/bin/entrypoint.sh
EXPOSE 143 4190 24 587
CMD ["/usr/local/bin/entrypoint.sh"]

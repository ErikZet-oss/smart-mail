#!/bin/bash
# Minimal sendmail for Dovecot vacation auto-replies on the local imap-test server only.
# Delivers stdin to the first recipient via dovecot-lda (no external MTA).
set -euo pipefail
recip=""
while [ $# -gt 0 ]; do
  case "$1" in
    -i|-t|-oi|-o*) shift ;;
    -f) shift; [ $# -gt 0 ] && shift ;;
    -*) shift ;;
    *)
      recip="$1"
      shift
      break
      ;;
  esac
done
if [ -z "${recip}" ]; then
  exit 0
fi
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat >"$tmp"
# Quiet LDA: dovecot -F logging uses /dev/stdout which is unavailable for this helper.
export LOGERR_LOGFILE=/tmp/vacation-lda.log
exec /usr/lib/dovecot/dovecot-lda -d "$recip" <"$tmp" 2>>/tmp/vacation-lda.log

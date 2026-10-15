#!/usr/bin/env bash
# Run in Ubuntu. Targets are fixed to this local lab.
set -uo pipefail

MODE=${1:-normal}
ALIVE=${2:-backend-1}
CA_FILE=${CA_FILE:-/etc/nginx/lab1/tls/lab1.crt}
if [[ "$MODE" != normal && "$MODE" != failover ]]; then
    echo "Usage: bash check.sh normal | failover backend-1|backend-2"
    exit 2
fi
if [[ "$ALIVE" != backend-1 && "$ALIVE" != backend-2 ]]; then
    echo "Expected backend-1 or backend-2"
    exit 2
fi
if [[ ! -r "$CA_FILE" ]]; then
    echo "Certificate is not readable: $CA_FILE"
    exit 2
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
HDR="$TMP/headers"
BODY="$TMP/body"
FAIL=0
PASS=0
CURL=(curl -sS --noproxy '*' --connect-timeout 2 --max-time 8
    --cacert "$CA_FILE"
    --resolve notes.test:80:127.0.0.1
    --resolve notes.test:443:127.0.0.1
    --resolve second.test:80:127.0.0.1
    --resolve second.test:443:127.0.0.1
    --resolve unknown.test:80:127.0.0.1)

ok() { echo "PASS: $*"; PASS=$((PASS + 1)); }
bad() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }
fetch() {
    CODE=$("${CURL[@]}" -D "$HDR" -o "$BODY" -w '%{http_code}' "$@")
    if [[ $? -ne 0 ]]; then CODE=000; fi
}
header() {
    awk -v name="$1" '
        tolower($1) == tolower(name ":") {
            sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); print
        }' "$HDR"
}
code_is() {
    if [[ "$CODE" == "$1" ]]; then ok "$2: HTTP $CODE";
    else bad "$2: expected $1, got $CODE"; fi
}
body_has() {
    if [[ $(cat "$BODY") == *"$1"* ]]; then ok "$2";
    else bad "$2: missing marker $1"; fi
}
body_lacks() {
    if [[ $(cat "$BODY") != *"$1"* ]]; then ok "$2";
    else bad "$2: leaked marker $1"; fi
}

echo "Local nginx lab; mode=$MODE; UTC=$(date -u +%FT%TZ)"
echo "TLS is checked with --cacert; --insecure is not used."
# Drain the previous finite rate-limit test before starting.
sleep 3

if [[ "$MODE" == normal ]]; then
    fetch -I http://notes.test/
    code_is 301 "HTTP to HTTPS"
    if [[ $(header Location) == https://notes.test/ ]]; then
        ok "Location: https://notes.test/"
    else bad "Unexpected Location: $(header Location)"; fi
    fetch -I http://second.test/
    code_is 301 "Second host redirects to HTTPS"
    if [[ $(header Location) == https://second.test/ ]]; then
        ok "Second host Location"
    else bad "Unexpected second-host Location"; fi
fi

fetch https://notes.test/
code_is 200 "HTTPS frontend"
body_has LAB1_NOTES_PROJECT "Notes frontend marker"
if [[ -z $(header X-Backend-ID) && $(header X-Site) == notes ]]; then
    ok "Frontend response has X-Site and no backend ID"
else bad "Unexpected frontend headers"; fi

IDS="$TMP/ids"
: > "$IDS"
for n in $(seq 1 10); do
    fetch https://notes.test/api/health
    ID=$(header X-Backend-ID)
    echo "API request $n: HTTP $CODE, X-Backend-ID=$ID"
    if [[ "$CODE" != 200 ]]; then bad "API request $n: HTTP $CODE"; fi
    if [[ "$MODE" == failover ]]; then
        if [[ "$ID" != "$ALIVE" ]]; then bad "Expected $ALIVE, got $ID"; fi
    elif [[ "$ID" != backend-1 && "$ID" != backend-2 ]]; then
        bad "Unknown or missing backend ID: $ID"
    fi
    printf '%s\n' "$ID" >> "$IDS"
    sleep 0.3
done
if [[ "$MODE" == normal ]]; then
    SEEN=$(sort -u "$IDS" | tr '\n' ' ')
    if [[ "$SEEN" == 'backend-1 backend-2 ' ]]; then
        ok "Both backend IDs observed"
    else bad "Expected both backend IDs; got: $SEEN"; fi
else
    echo "Expected only the surviving instance: $ALIVE"
fi
fetch https://notes.test/api/notes
code_is 200 "Read notes from the shared database"

if [[ "$MODE" == normal ]]; then
    fetch https://notes.test/static/style.css
    code_is 200 "nginx serves CSS"
    if [[ $(header Content-Type) == text/css* ]]; then ok "CSS MIME type";
    else bad "Wrong CSS MIME type"; fi

    fetch https://notes.test/docs
    code_is 301 "Canonical /docs/ path"
    fetch https://notes.test/docs/
    code_is 200 "alias directory"
    body_has LAB1_DOCS "alias content"
    fetch https://notes.test/docs/guide.txt
    code_is 200 "File from alias directory"
    body_has LAB1_DOCS_FILE "alias file marker"

    for path in /admin /admin/ /admin/index.html; do
        fetch "https://notes.test$path"
        code_is 401 "Basic Auth without credentials: $path"
        if [[ $(header WWW-Authenticate) == Basic* ]]; then
            ok "WWW-Authenticate header: $path"
        else bad "No Basic Auth challenge: $path"; fi
    done

    fetch https://second.test/
    code_is 200 "Second virtual host"
    body_has LAB1_SECOND_PROJECT "Second-project content"
    body_lacks LAB1_NOTES_PROJECT "No notes-project content on second.test"
    fetch https://second.test/api/health
    code_is 404 "Second host does not proxy the notes API"
    fetch -H 'Host: second.test' https://notes.test/
    code_is 200 "Known alternative Host with notes.test TLS SNI"
    body_has LAB1_SECOND_PROJECT "Host selects only the second project"
    body_lacks LAB1_NOTES_PROJECT "Alternative Host does not leak notes"
    fetch -H 'Host: unknown.test' https://notes.test/
    code_is 421 "Unknown Host with valid notes.test TLS SNI"
    body_lacks LAB1_NOTES_PROJECT "Unknown Host does not leak notes"
    body_lacks LAB1_SECOND_PROJECT "Unknown Host does not leak second"
    fetch http://unknown.test/
    code_is 421 "Unknown HTTP virtual host"

    fetch https://notes.test/this-page-does-not-exist
    code_is 404 "Custom 404 retains the 404 status"
    body_has LAB1_CUSTOM_404 "Our custom 404 body"

    echo "Finite local rate test: 40 requests, at most 8 at once."
    sleep 3
    for n in $(seq 1 40); do
        (
            "${CURL[@]}" -o /dev/null -w '%{http_code}\n' \
                https://notes.test/api/health > "$TMP/rate-$n"
        ) &
        if (( n % 8 == 0 )); then wait; fi
    done
    wait
    cat "$TMP"/rate-* | sort | uniq -c
    REJECTED=$(awk '$1 == 429 {n++} END {print n+0}' "$TMP"/rate-*)
    OTHER=$(awk '$1 != 200 && $1 != 429 {n++} END {print n+0}' "$TMP"/rate-*)
    if (( REJECTED > 0 )); then ok "limit_req returned 429";
    else bad "No 429 observed; stop browser traffic and inspect limit_req"; fi
    if (( OTHER == 0 )); then ok "Rate-test statuses are only 200 and 429";
    else bad "Unexpected statuses in rate test"; fi
fi

echo "RESULT: PASS=$PASS FAIL=$FAIL"
if (( FAIL > 0 )); then exit 1; fi
exit 0

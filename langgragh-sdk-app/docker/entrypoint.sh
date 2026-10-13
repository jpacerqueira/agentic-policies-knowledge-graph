#!/bin/sh
set -eu

if policy-kg run \
  --policy-dir data/policies \
  --oscal-dir data/oscal \
  --organization data/organization.json
then
  touch /tmp/pipeline.ok
else
  status="$?"
  echo "pipeline failed with status ${status}" >&2
fi

exec policy-kg serve \
  --host 0.0.0.0 \
  --port 8080 \
  --oscal-dir data/oscal \
  --organization data/organization.json \
  --intake-dir submissions

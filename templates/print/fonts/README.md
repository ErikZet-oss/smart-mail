# Print fonts

`LiberationSansNarrow-Regular.ttf`, `LiberationSansNarrow-Bold.ttf` — Liberation Sans Narrow 1.07.5,
Copyright 2010 Oracle and/or its affiliates, licensed under the Liberation Fonts license
(https://fedoraproject.org/wiki/Licensing/LiberationFontLicense — GPLv2 with a font embedding exception).

They are metric-compatible with Arial Narrow, which the Money S4 print reports use (DOCUMENTS_SPEC §4.2).
The Docker image and CI install them into the system font directory so that the golden print tests
(`tests/test_print_golden.py`) render exactly like `fixtures/documents/*.png`. Do not replace them.

`LiberationSans-Regular.ttf`, `LiberationSans-Bold.ttf` — Liberation Sans 2.1.5 (Debian `fonts-liberation2`, the
same version as the Docker image), Copyright 2012 Red Hat, Inc., SIL Open Font License 1.1. Used by the
Prehlásenie o zhode (`conformity.html.j2`, ADR-015). Bundled so that CI, the image and a dev machine render the
golden file `fixtures/documents/conformity_sample.png` with the same font file.

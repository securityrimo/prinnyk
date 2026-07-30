# Required Reference Projects

The following projects are mandatory references for the Prinny 1 and
Prinny 2 Korean-patch toolchains.

## hancharacter

https://github.com/yazzang-homelab/hancharacter/blob/master/GUIDE.ko.md

Use for speaker identity, speech-style preservation, loss/invention
review, and human approval gates. Automated findings do not replace
human translation review.

## emucap

https://github.com/mcpads/emucap

Use for hash-bound PPSSPP runtime tests, screenshots, execution logs,
reproducible test cases, and regression evidence.

## create-kr-patch-template

https://github.com/mcpads/create-kr-patch-template

Use for immutable inputs, expected-write checks, protected regions,
registered diffs, deterministic builds, manifests, and fail-closed
application.

## GitHub checkpoints

After every completed major gate, commit and push code, schemas,
manifests, audit summaries, and reproducibility documents before
starting the next major gate.

Do not commit game ISOs, extracted copyrighted resources, BIOS files,
save states, or raw product builds.

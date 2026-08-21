# Third-party notices

Original VIREA integration code is offered under the scoped MIT terms in
`LICENSE`. The prompt-encoding sequence in
`src/virea_prism/offline_loader.py` was adapted from
`PRISM/prism/pipelines/prism_ar_t2m_pipeline.py` at the pinned source revision;
the upstream repositories do not publish usable licensing terms. The scoped
MIT notice therefore does not apply to that adapted sequence.

The runtime interoperates with external, user-installed artifacts from:

- PRISM source at revision `3c58bc5d946f0827171a3712ed36314f4b1a5186`;
- `ZeyuLing/PRISM-TP2M-1.4B` at revision `825daaa27f4f3845eb0978674c3acb378a12cda6`;
- `google/umt5-xxl` tokenizer files at revision `66cb9e7e85526fe440a945569e42c72fb6cbc0ad`;
- `ZeyuLing/MotionHub` statistics at revision `c3f6c8eb8a4ba9e5ca521cdc0af9264756b66726`.

The pinned PRISM repositories do not currently publish usable redistribution
terms. VIREA therefore does not redistribute those source or model artifacts,
and the complete runtime remains private/internal or source-review-only until
the adapted sequence is licensed or replaced by an independently documented
implementation. Installation requires explicit user acceptance and uses
external assets from their declared roots.

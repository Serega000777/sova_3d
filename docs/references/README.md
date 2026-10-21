# Sova 3D reference archive

This directory is the durable repository home for the owner's numbered UI/product
references. It keeps the numbered product catalogues and additional visual-concept
namespaces separate:

- `AUTH01`–`AUTH03`: authorization-screen concepts;
- `G01`–`G10`: light/green workspace visual-direction concepts;
- `O01`–`O10`: editor/workspace composition references;
- `01`–`100`: the complete product-screen catalogue;
- `M01`–`M10`: the marketplace catalogue.

`CATALOG.md` is the canonical number-to-title list. Images are added without changing their
content under `images/auth/`, `images/g/`, `images/o/`, `images/product/`, and
`images/marketplace/`. Each image filename starts with its catalogue id, for example `O03.png`,
`51-02.png`, or `M08.png`. Multiple images for one entry use a two-digit suffix. Original
file extensions are preserved.

The recovered 2026-10-21 corpus contains 138 unique image files: 3 authorization concepts,
10 green/light concepts, 10 editor/workspace compositions, complete image coverage for product
IDs `01`–`100`, complete image coverage for marketplace IDs `M01`–`M10`, and five retained
alternate/conflicting product-number variants. `MANIFEST.tsv` is the authoritative byte-level
inventory; its `sequence` column distinguishes multiple images carrying the same visible ID.

For every received batch:

1. calculate SHA-256 before renaming;
2. reject exact duplicates and keep the first retained source;
3. add the image path and hash to `MANIFEST.tsv`;
4. mark missing catalogue numbers explicitly rather than guessing their images;
5. update the inspected-image count in the relevant analysis document only after visual review.

The first source list was received on 2026-10-21 as `список названий.txt`, SHA-256
`fc5e716eaa00397c302f2ea9209f2b288231d69f749c03a0327b7ce77edf2e48`.

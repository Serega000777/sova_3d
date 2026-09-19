# Feature registry — addendum

Features the product owner added after the engineering pack (`v2/01_FEATURE_REGISTRY_80.docx`,
F-001..F-080). Same rules: an ID is never silently removed or de-scoped; every PR names one.

| ID | Feature | Description | Domain | Phase | Added |
|---|---|---|---|---|---|
| F-081 | Cut into parts | Any model — an imported statuette included — is cut with planes into parts that print: every part watertight with a flat cut face, dowel holes on both sides of each cut (the dowels come along as parts), the parts laid out on the bed cut-face-down, "fit my printer" for the fewest cuts that make every part fit the bed. A mesh that is not a closed volume is repaired first. Reachable by request and by the sentence ("разрежь на 3 части", "cut it in half so it fits my printer"). | Printing / Engineering | V1 | 2026-09-19 |
| F-082 | Scanner station | A dedicated 3D scanner — handheld, structured light, a depth camera on a turntable — streams metric fragments (meshes or point clouds, each with its pose) into a live scan session; the Scanner section shows them arriving; the platform fuses them (union of closed fragments, stitching of open shells, voxel meshing of point clouds), drops floating specks, closes small holes and reports the scale as the device's measurement; the model lands in the workspace to refine, check and print. Devices connect through the bridge (`tools/scanner-bridge`): a folder driver for any vendor software that saves files, an Intel RealSense driver, a simulated turntable. Extends F-002. | Scan / Physical AI | V2 | 2026-09-19 |

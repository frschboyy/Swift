---
name: tidy-downloads
description: Sort the Downloads folder into subfolders by type and age, after showing the plan. Use when the user asks to tidy, clean up, organise or sort their downloads.
license: MIT
metadata:
  swift-manifest: swift.yaml
---

# Tidy downloads

1. List the files directly in Downloads (not in subfolders). Skip files changed in the last 24 hours: they may still be in use.
2. Sort each file by extension:
   - documents (pdf, docx, xlsx, pptx, txt, md) → `Documents/From downloads`
   - images (png, jpg, jpeg, gif, webp, heic) → `Pictures/From downloads`
   - installers (exe, msi) older than 30 days → `Downloads/Old installers`
   - archives (zip, 7z, rar) → `Downloads/Archives`
3. For anything else, decide from the name whether it belongs to one of these groups. If unsure, leave it where it is.
4. Show the whole plan as a table (file, from, to) and wait for approval before moving anything.
5. Move, never delete. Keep a list of the moves so they can be undone.

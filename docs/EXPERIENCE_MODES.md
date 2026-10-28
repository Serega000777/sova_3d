# Beginner and professional interface modes

Sova stores one account-level `experience_mode` in the existing user flags document. The API
accepts only `beginner` or `professional`; absent or untrusted legacy values fail safely to
`beginner`. No database migration is required.

- **Beginner** is the default. Web Studio opens its guided/simple surface. Mobile mesh editing
  keeps direct move/scale/rotate and selection controls while hiding the dense exact-CAD strip.
- **Professional** opens the advanced Studio surface by default and shows exact CAD, scene,
  layer and inspection entry points on mobile.
- The Studio switch remains available per project as a temporary view override. It does not
  silently rewrite the account preference.
- The mode changes information density only. It never changes the account plan or bypasses
  server-side entitlements; a professional interface may still show a legitimate Pro lock.

The preference is edited in web Settings and the mobile Profile and follows the signed-in user
across devices through `PATCH /api/v1/auth/me`.

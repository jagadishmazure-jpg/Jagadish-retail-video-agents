# Privacy notes (not legal advice)
- **Biometric laws.** Some US states have strict biometric privacy laws (Illinois-style rules require written consent
  before collecting face geometry, and allow lawsuits per violation). Texas and Washington have their own rules, and
  some cities restrict face recognition in stores. This design avoids the whole category: it never collects face
  geometry, embeddings, gait or voice, and rejects such fields at input.
- **Notice.** Post clear signs that cameras and analytics are in use.
- **Minimisation.** Store only counts, times and zones; clips only as blurred references.
- **Retention.** Unflagged clips 3 days, reviewed 30 days, confirmed incidents 90 days, then purge.
- **Employees.** Cashiers appear only as pseudonymous tokens; check labor and union rules before monitoring staff.
- **No accusation.** An alert is a reason to look, never a finding. Only a manager decides, and the store's normal
  policy and the law decide what happens next.
- Get a lawyer to review the setup before any real pilot.

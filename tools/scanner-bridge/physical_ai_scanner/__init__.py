"""Scanner bridge (F-082): a dedicated 3D scanner on the desk becomes a live scan session.

The scanner's own software does what it is good at — tracking, meshing — and this bridge
does the rest: it opens a session on the platform, streams every fragment the device
delivers as it arrives (so the Scanner section shows the model growing), then finalizes and
hands the fused, metric model to the workspace for editing and printing.

Drivers speak to the hardware; the rest of the bridge never does.
"""

__version__ = "0.1.0"

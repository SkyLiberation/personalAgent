"""Kernel layer: shared contracts, config, and observability primitives.

The kernel is the bottom of the dependency stack. Every other layer may depend
on it; the kernel depends on nothing above it. It holds pure data contracts and
Protocols (``kernel.contracts``) that higher layers — and crucially the infra
layer beneath them — share without creating upward dependencies.
"""

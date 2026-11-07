**Language:** English · [Português](pci_protocol_pending_validation.pt-BR.md)

# Pending scientific item — physical LS protocol

CarcinoIndex stores only the manual LS supplied by the user: 0, 1, 2 or 3, or
NULL when the specialist indicates that LS cannot be determined. The system does
not convert pixel area to centimeters and does not derive LS from the mask
produced by SAM 2.

Before describing physical limits in the TCC or automating the classification,
the size criteria adopted by the project must be validated with specialists and
tied to an explicit reference and protocol version. Until that validation, the
API uses:

- `protocol_id = "sugarbaker_pci"`;
- `protocol_version = "project-defined-v1"`.

The annotation strategy, the governed clinical dataset, the inter-observer
evaluation and clinical validation also remain pending.

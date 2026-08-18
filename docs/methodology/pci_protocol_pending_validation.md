# Pendência científica — protocolo físico de LS

A M3 armazena exclusivamente o LS manual 0, 1, 2 ou 3 informado pelo usuário.
Ela não converte área em pixels para centímetros e não deriva LS da máscara
produzida pelo SAM 2.

Antes de descrever limites físicos no TCC ou automatizar a classificação, os
critérios de tamanho adotados pelo projeto precisam ser homologados com
especialistas e vinculados a uma referência e versão de protocolo explícitas.
Até essa homologação, a API usa:

- `protocol_id = "sugarbaker_pci"`;
- `protocol_version = "project-defined-v1"`.

Também permanecem pendentes a estratégia de anotação, o conjunto de dados
clínicos governado, a avaliação interobservador e a validação clínica.

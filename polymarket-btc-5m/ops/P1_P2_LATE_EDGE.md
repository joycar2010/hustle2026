# P1 / P2 — late_edge structure (after P0 band cut)

## P1
| Lever | Behavior |
|-------|----------|
| `OPENING_GAP_MAX_ENTRY_PRICE=0.78` | Gap phase tighter than late (`MAX_ENTRY=0.79`) |
| `MIN_NET_EDGE_HIGH=0.12` @ `HIGH_ASK_THRESHOLD=0.80` | Defense if max entry is raised later |
| `CONFIRM_CHECKS_HIGH=5` | Extra confirms on high asks |
| Asymmetric Δ | `UP_MIN=20`, `DOWN_MAX=-30` |
| Asymmetric lead | `UP_LEAD_MIN_BP=1.5`, `DOWN_LEAD_MIN_BP=3.0` |

## P2
| Lever | Behavior |
|-------|----------|
| `LEAD_EDGE_MARGIN_DOWN=0.07` | DOWN harder vs BTC hold table |
| `SIZE_SCALE_ENABLED` | `size ∝ (1-ask)/(1-0.75)` |
| eth5m / sol5m | `lead_table_enabled=False`, `max_entry=0.78`, gap cap 0.76 |

BTC hold table stays on for BTC A only; altcoins use Δ/bp until asset-specific tables exist.

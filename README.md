# home-finance for Home Assistant

A [HACS](https://hacs.xyz) custom integration that turns the read-only **Integration API** of a
self-hosted [home-finance](https://github.com/wouterdamman/home-finance) server into Home
Assistant devices and sensors: kids' savings, savings pots, and the monthly and yearly budget
totals. It replaces the hand-written `rest:` configuration from the home-finance integrations
guide.

- Config flow: base URL + token, validated against `GET /info`.
- One device per kid, one per savings pot, and one **Household** device for the totals.
- Kids and pots are discovered on every refresh. New ones appear without a reload; archived ones
  are removed.
- Read-only. Nothing is ever written to home-finance.
- Polls every 15 minutes by default (configurable, minimum 5).

Requires **home-finance 1.26.0 or newer** and Home Assistant 2026.10.4 or newer.

## Installation (HACS)

1. In Home Assistant open **HACS**, use the three-dot menu at the top right and choose
   **Custom repositories**.
2. Add `https://github.com/wouterdamman/ha-home-finance` with type **Integration**.
3. Search HACS for **home-finance**, open it and click **Download**.
4. Restart Home Assistant.
5. Go to **Settings > Devices & services > Add integration** and choose **home-finance**.
6. Enter the base URL of your server (for example `https://budget.app.example.com`) and the
   token (see below).

## Creating a token

1. Sign in to home-finance as an admin and open **Settings > Integrations**.
2. Give the token a name, for example `Home Assistant`. It becomes the integration's title.
3. Tick only the scopes you want in Home Assistant:

   | Scope | Gives |
   |---|---|
   | `kids:read` | a device per kid and the household kid totals |
   | `pots:read` | a device per savings pot and the household pot totals |
   | `periods:read` | this month's income, expenses and surplus |
   | `years:read` | this year's income, expenses and surplus |

4. Pick an expiry. Every token expires: 1 hour to 2 years, default 1 year.
5. Confirm the step-up re-authentication and copy the `hf_...` token. It is shown once.

A token's scopes cannot be changed later. To add or remove a scope, create a new token and use
**Reconfigure** on the integration.

### Expiry and rotation

The API does not expose a token's expiry, so this integration cannot warn you in advance. The
token list in home-finance shows each token's expiry; rotate a few weeks before:

1. Create a new token with the same scopes.
2. In Home Assistant open the integration, choose **Reconfigure** and paste the new token.
3. Revoke the old token in home-finance.

If a token expires or is revoked anyway, the server answers `401` and Home Assistant shows a
**re-authenticate** prompt for the integration. Enter a new token there.

## Entities

Entity IDs below are what Home Assistant generates on an English-language install (device name +
entity name). Kid and pot device names come from home-finance, for example `Sam` or `New car`.
Money sensors are in EUR with 2 decimals; amounts come from the API as integer cents.

Sensors marked *disabled* exist but are disabled by default. Enable them under the device if you
need them.

### `kids:read`: one device per kid

| Entity | Value |
|---|---|
| `sensor.<kid>_total` | Whole balance (state class `total`) |
| `sensor.<kid>_saved_by_us` | "Door ons gespaard" sub-pot (`total`) |
| `sensor.<kid>_own_money` | "Eigen geld" sub-pot (`total`) |
| `sensor.<kid>_net_this_month` / `_net_this_year` | Net movement this calendar month/year (Europe/Amsterdam) |
| `sensor.<kid>_deposited_this_month` / `_deposited_this_year` | Deposits this month/year |
| `sensor.<kid>_bank_balance` | Balance last reported by the bank (`total`); unknown if none recorded. Attribute `reported_balance_date` |
| `sensor.<kid>_bank_difference` | Ledger minus bank; unknown if no bank balance is recorded. Attribute `reported_balance_date` |
| `sensor.<kid>_last_entry` | Date of the latest entry; attributes `type`, `owner`, `amount` (EUR, signed) |
| `sensor.<kid>_last_entry_amount` | Signed amount of the latest entry |
| *disabled* | `_opening_balance`, `_total_deposits`, `_total_withdrawals`, `_total_adjustments`, `_withdrawn_this_month`, `_withdrawn_this_year`, `_saved_by_us_net_this_month/year`, `_own_money_net_this_month/year` |

Household device: `sensor.household_kids_total`, `sensor.household_kids_saved_by_us`,
`sensor.household_kids_own_money` (all `total`).

### `pots:read`: one device per savings pot

| Entity | Value |
|---|---|
| `sensor.<pot>_balance` | Balance (`total`) |
| `sensor.<pot>_target` | Savings goal; unknown without a goal |
| `sensor.<pot>_progress` | Progress towards the goal in %, not capped at 100 |
| `sensor.<pot>_remaining` | Still to save |
| `sensor.<pot>_needed_per_month` | Needed per month to reach the goal by its date; unknown without a date |
| `sensor.<pot>_months_left` | Months until the goal date |
| `sensor.<pot>_target_date` | Goal date |
| `sensor.<pot>_allocated_this_month` | Surplus share allocated this month (usually 0 until the month is closed) |
| `sensor.<pot>_net_this_month` / `_net_this_year` | Net movement this month/year |
| `sensor.<pot>_split` | Share of the monthly surplus in %; attributes `period_year`, `period_month`, `period_status` |
| `sensor.<pot>_last_entry` | Date of the latest entry; attributes `type`, `amount` |
| `binary_sensor.<pot>_goal_reached` | On when the balance has reached the goal |
| *disabled* | `_opening_balance`, `_total_allocations`, `_total_deposits`, `_total_withdrawals`, `_total_carried_over`, `_total_adjustments`, `_allocated_this_year`, `_deposited_this_month`, `_withdrawn_this_month` |

Household device: `sensor.household_pots_total` (`total`), `sensor.household_pots_target_total`.

### `periods:read`: household device

`sensor.household_month_income`, `sensor.household_month_expenses`,
`sensor.household_month_surplus` (can be negative) and `sensor.household_month_status`
(`open`/`closed`). All four carry the attributes `year`, `month`, `is_current_month` and
`closed_at`. When the current month has no period yet, home-finance falls back to an earlier
one and `is_current_month` is `false`. Before any period exists these sensors are unavailable.

### `years:read`: household device

`sensor.household_year_income`, `sensor.household_year_expenses`,
`sensor.household_year_surplus`, `sensor.household_year_average_monthly_surplus`
(year-to-date, open months included); *disabled*: `_year_open_periods`, `_year_closed_periods`.

### Why most month and year figures have no state class

Balances use `state_class: total`. Month and year figures reset at every period boundary, and
Home Assistant's monetary sensors only allow `total`, which would turn those resets into
misleading long-term statistics. They therefore have no state class: they still have history,
but no long-term statistics.

## Example Lovelace cards

```yaml
type: grid
columns: 3
square: false
cards:
  - type: tile
    entity: sensor.household_kids_total
    name: All kids
  - type: tile
    entity: sensor.sam_total
    name: Sam
    icon: mdi:piggy-bank
  - type: tile
    entity: sensor.noor_total
    name: Noor
    icon: mdi:piggy-bank
  - type: tile
    entity: sensor.household_pots_total
    name: All pots
  - type: tile
    entity: sensor.vacation_balance
    name: Vacation
    icon: mdi:beach
  - type: tile
    entity: sensor.household_month_surplus
    name: Surplus this month
```

```yaml
type: gauge
entity: sensor.vacation_progress
name: Vacation
min: 0
max: 100
needle: true
severity:
  red: 0
  yellow: 40
  green: 80
```

## Errors and behaviour

| Server answer | What the integration does |
|---|---|
| `401` | Starts re-authentication. Enter a new token. |
| `403 insufficient_scope` | That scope's entities become unavailable and a repair issue explains it. Other scopes keep working. |
| `404` on a kid or pot | Treated as renamed or archived: the list is fetched again and the device follows the list. |
| `404` on a whole endpoint | The server is older than 1.26.0: that scope is skipped with a log line. |
| `500`, timeout, DNS or TLS error | Entities become unavailable and the next poll retries. Never a re-authentication. |

## Renames and slugs (known limitation)

The API identifies kids and pots only by a **slug** derived from the name, and has no stable id.
The slug changes when a kid or pot is renamed, and when a second one with the same name appears
(`sam` becomes `sam-12` and `sam-31`). This integration uses the slug in the device and entity
unique IDs, so **a rename creates a new device with new entities**, and the old device is
removed. Customisations of the old entities (names, icons, areas, dashboard references) do not
carry over, and their history stays with the old entity IDs. Display names are deliberately not
used to match devices, as names are not unique.

## Privacy

Anyone who can use your Home Assistant can see these sensors: Home Assistant has no per-entity
permissions. Only grant the scopes you are happy to show to everyone with access. The token is
stored in Home Assistant's config entry storage, is never logged, and is redacted from
diagnostics along with the server URL and kid and pot names. Use HTTPS for anything outside your
own network.

## Development

```bash
make venv    # uv venv with Python 3.14 and the test requirements
make lint    # ruff check + ruff format --check
make test    # pytest with coverage
```

`scripts/smoke.py` is an optional live check against a real server. It reads `HF_BASE_URL` and
`HF_TOKEN` from the environment, calls `/info` and the list endpoints, and never prints the token.

Releases are cut by release-please from Conventional Commits.

## License

MIT

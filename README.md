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
- You choose which data to fetch: kids, savings pots, month figures, year figures.
- Only a compact set of entities is enabled by default; the rest can be enabled per entity.
- Polls every 15 minutes by default (configurable, minimum 5).

Requires **home-finance 1.26.0 or newer** and Home Assistant 2026.11.0 or newer. (The test
suite runs against 2026.10.4, the newest version `pytest-homeassistant-custom-component`
supports so far.)

## Installation (HACS)

1. In Home Assistant open **HACS**, use the three-dot menu at the top right and choose
   **Custom repositories**.
2. Add `https://github.com/wouterdamman/ha-home-finance` with type **Integration**.
3. Search HACS for **home-finance**, open it and click **Download**.
4. Restart Home Assistant.
5. Go to **Settings > Devices & services > Add integration** and choose **home-finance**.
6. A form opens. Enter:
   - the base URL of your server, for example `https://budget.app.example.com`;
   - the token (see below). It is a password field and is stored as a secret;
   - the name of the **Household** device that holds the totals. The suggestion is `Huishouden`
     on a Dutch-language Home Assistant and `Household` otherwise. The household entity IDs are
     derived from it, for example `sensor.huishouden_kinderen_totaal`.
7. Next, tick the data to fetch: **Kids**, **Savings pots**, **Month figures**, **Year figures**.
   Only the scopes the token holds are listed, all ticked by default. Data you leave out is not
   requested and gets no devices or entities. Change it later under **Configure**, together with
   the update interval.

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
2. In Home Assistant open the integration, choose **Reconfigure** and paste the new token. The
   same form also changes the server URL and the Household device name.
3. Revoke the old token in home-finance.

If a token expires or is revoked anyway, the server answers `401` and Home Assistant shows a
**re-authenticate** prompt for the integration. Enter a new token there.

## Entities

Home Assistant builds an entity ID from the device name and the entity name, in the language of
your installation. On a Dutch install the names, and therefore the entity IDs, are Dutch: a kid
named `Sam` gets `sensor.sam_totaal`, and with the Household device named `Huishouden` the kids
total is `sensor.huishouden_kinderen_totaal`. On an English install these are `sensor.sam_total`
and `sensor.household_kids_total`. `<device>` below is the kid's or pot's name from home-finance
(`sam`, `new_car`) or the Household device name you chose. Entity IDs are fixed once created;
renaming entities in Home Assistant is up to you.

Money sensors are in EUR with 2 decimals; amounts come from the API as integer cents.

Only a compact set is enabled by default (column *Default*), so the same figure does not show up
under several names. Every other entity exists but starts disabled: open the device in Home
Assistant and enable the ones you want. Upgrading from v0.2.0 disables the entities that are no
longer in the default set, except ones you enabled or disabled yourself.

### `kids:read`: one device per kid

| English install | Dutch install | Value | Default |
|---|---|---|---|
| `sensor.<device>_total` | `sensor.<device>_totaal` | Whole balance (`total`) | on |
| `sensor.<device>_saved_by_us` | `sensor.<device>_door_ons_gespaard` | "Door ons gespaard" sub-pot (`total`) | on |
| `sensor.<device>_own_money` | `sensor.<device>_eigen_geld` | "Eigen geld" sub-pot (`total`) | on |
| `sensor.<device>_net_this_month` | `sensor.<device>_netto_deze_maand` | Net movement this calendar month (Europe/Amsterdam) | off |
| `sensor.<device>_net_this_year` | `sensor.<device>_netto_dit_jaar` | Net movement this calendar year | off |
| `sensor.<device>_deposited_this_month` | `sensor.<device>_gestort_deze_maand` | Deposits this month | off |
| `sensor.<device>_deposited_this_year` | `sensor.<device>_gestort_dit_jaar` | Deposits this year | off |
| `sensor.<device>_bank_balance` | `sensor.<device>_banksaldo` | Balance last reported by the bank (`total`); unknown if none recorded | off |
| `sensor.<device>_bank_difference` | `sensor.<device>_verschil_met_bank` | Ledger minus bank; unknown if no bank balance is recorded. Attribute `reported_balance_date` | on |
| `sensor.<device>_last_entry` | `sensor.<device>_laatste_boeking` | Date of the latest entry; attributes `type`, `amount` (EUR, signed) and for kids `owner` | on |
| `sensor.<device>_last_entry_amount` | `sensor.<device>_bedrag_laatste_boeking` | Signed amount of the latest entry | off |
| `sensor.<device>_opening_balance` | `sensor.<device>_beginsaldo` | Sum of opening balances | off |
| `sensor.<device>_total_deposits` | `sensor.<device>_totaal_gestort` | All deposits | off |
| `sensor.<device>_total_withdrawals` | `sensor.<device>_totaal_opgenomen` | All withdrawals | off |
| `sensor.<device>_total_adjustments` | `sensor.<device>_totaal_correcties` | All adjustments | off |
| `sensor.<device>_withdrawn_this_month` | `sensor.<device>_opgenomen_deze_maand` | Withdrawals this month | off |
| `sensor.<device>_withdrawn_this_year` | `sensor.<device>_opgenomen_dit_jaar` | Withdrawals this year | off |
| `sensor.<device>_saved_by_us_net_this_month` | `sensor.<device>_door_ons_gespaard_netto_deze_maand` | Saved by us, net this month | off |
| `sensor.<device>_saved_by_us_net_this_year` | `sensor.<device>_door_ons_gespaard_netto_dit_jaar` | Saved by us, net this year | off |
| `sensor.<device>_own_money_net_this_month` | `sensor.<device>_eigen_geld_netto_deze_maand` | Own money, net this month | off |
| `sensor.<device>_own_money_net_this_year` | `sensor.<device>_eigen_geld_netto_dit_jaar` | Own money, net this year | off |

On the Household device:

| English install | Dutch install | Value | Default |
|---|---|---|---|
| `sensor.<device>_kids_total` | `sensor.<device>_kinderen_totaal` | All kids together (`total`) | on |
| `sensor.<device>_kids_saved_by_us` | `sensor.<device>_kinderen_door_ons_gespaard` | All kids, saved by us (`total`) | off |
| `sensor.<device>_kids_own_money` | `sensor.<device>_kinderen_eigen_geld` | All kids, own money (`total`) | off |

### `pots:read`: one device per savings pot

Goal entities only exist for a pot that has a goal, and the date-based ones only when the goal
has a date. They appear when you set a goal in home-finance and disappear when you remove it, so
a pot without a goal has no sensors stuck on `unknown`. The same holds for the split.

| English install | Dutch install | Value | Default |
|---|---|---|---|
| `sensor.<device>_balance` | `sensor.<device>_saldo` | Balance (`total`) | on |
| `sensor.<device>_target` | `sensor.<device>_spaardoel` | Savings goal; only for a pot with a goal | off |
| `sensor.<device>_progress` | `sensor.<device>_voortgang` | Progress towards the goal in %, not capped at 100; only for a pot with a goal | on |
| `sensor.<device>_remaining` | `sensor.<device>_nog_te_sparen` | Still to save; only for a pot with a goal | off |
| `sensor.<device>_needed_per_month` | `sensor.<device>_nodig_per_maand` | Needed per month to reach the goal by its date; only for a goal with a date | off |
| `sensor.<device>_months_left` | `sensor.<device>_maanden_te_gaan` | Months until the goal date; only for a goal with a date | off |
| `sensor.<device>_target_date` | `sensor.<device>_doeldatum` | Goal date; only for a goal with a date | off |
| `sensor.<device>_allocated_this_month` | `sensor.<device>_toegewezen_deze_maand` | Surplus share allocated this month (usually 0 until the month is closed) | off |
| `sensor.<device>_net_this_month` | `sensor.<device>_netto_deze_maand` | Net movement this calendar month (Europe/Amsterdam) | off |
| `sensor.<device>_net_this_year` | `sensor.<device>_netto_dit_jaar` | Net movement this calendar year | off |
| `sensor.<device>_split` | `sensor.<device>_verdeling` | Share of the monthly surplus in %; attributes `period_year`, `period_month`, `period_status`; only for a pot with a split | off |
| `sensor.<device>_last_entry` | `sensor.<device>_laatste_boeking` | Date of the latest entry; attributes `type`, `amount` (EUR, signed) and for kids `owner` | off |
| `sensor.<device>_opening_balance` | `sensor.<device>_beginsaldo` | Sum of opening balances | off |
| `sensor.<device>_total_allocations` | `sensor.<device>_totaal_toegewezen` | All allocations | off |
| `sensor.<device>_total_deposits` | `sensor.<device>_totaal_gestort` | All deposits | off |
| `sensor.<device>_total_withdrawals` | `sensor.<device>_totaal_opgenomen` | All withdrawals | off |
| `sensor.<device>_total_carried_over` | `sensor.<device>_totaal_doorgeschoven` | All carry-over out | off |
| `sensor.<device>_total_adjustments` | `sensor.<device>_totaal_correcties` | All adjustments | off |
| `sensor.<device>_allocated_this_year` | `sensor.<device>_toegewezen_dit_jaar` | Allocated this year | off |
| `sensor.<device>_deposited_this_month` | `sensor.<device>_gestort_deze_maand` | Deposits this month | off |
| `sensor.<device>_withdrawn_this_month` | `sensor.<device>_opgenomen_deze_maand` | Withdrawals this month | off |
| `binary_sensor.<device>_goal_reached` | `binary_sensor.<device>_spaardoel_bereikt` | On when the balance has reached the goal; only for a pot with a goal | off |

On the Household device:

| English install | Dutch install | Value | Default |
|---|---|---|---|
| `sensor.<device>_pots_total` | `sensor.<device>_potjes_totaal` | All pots together (`total`) | on |
| `sensor.<device>_pots_target_total` | `sensor.<device>_potjes_spaardoel_totaal` | Sum of the goals of pots that have one | off |

### `periods:read`: Household device

| English install | Dutch install | Value | Default |
|---|---|---|---|
| `sensor.<device>_month_income` | `sensor.<device>_inkomsten_deze_maand` | Income this month | on |
| `sensor.<device>_month_expenses` | `sensor.<device>_uitgaven_deze_maand` | Expenses this month | on |
| `sensor.<device>_month_surplus` | `sensor.<device>_overschot_deze_maand` | Surplus this month (can be negative) | on |
| `sensor.<device>_month_status` | `sensor.<device>_status_maand` | `open` or `closed` | off |

All four carry the attributes `year`, `month`, `is_current_month` and `closed_at`. When the
current month has no period yet, home-finance falls back to an earlier one and
`is_current_month` is `false`. Before any period exists these sensors are unavailable.

### `years:read`: Household device

| English install | Dutch install | Value | Default |
|---|---|---|---|
| `sensor.<device>_year_income` | `sensor.<device>_inkomsten_dit_jaar` | Income this year (year-to-date) | off |
| `sensor.<device>_year_expenses` | `sensor.<device>_uitgaven_dit_jaar` | Expenses this year | off |
| `sensor.<device>_year_surplus` | `sensor.<device>_overschot_dit_jaar` | Surplus this year | on |
| `sensor.<device>_year_average_monthly_surplus` | `sensor.<device>_gemiddeld_overschot_per_maand_dit_jaar` | Surplus divided by the number of periods so far | off |
| `sensor.<device>_year_open_periods` | `sensor.<device>_open_maanden_dit_jaar` | Open months this year | off |
| `sensor.<device>_year_closed_periods` | `sensor.<device>_afgesloten_maanden_dit_jaar` | Closed months this year | off |

### Why most month and year figures have no state class

Balances use `state_class: total`. Month and year figures reset at every period boundary, and
Home Assistant's monetary sensors only allow `total`, which would turn those resets into
misleading long-term statistics. They therefore have no state class: they still have history,
but no long-term statistics.

## Example Lovelace cards

Entity IDs as on an English install; on a Dutch install use the Dutch IDs from the tables above
(`sensor.huishouden_kinderen_totaal`, `sensor.sam_totaal`, `sensor.vacation_voortgang`, …).

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

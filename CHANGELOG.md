### 1.4.2: 2026-08-19

* Point recipe entries at the gram measure
* Fix recipe entries reading 100x wrong in the app
* Add a gram measure to recipes that lack one
* Show the diary's own number for dangling measures

### 1.4.1: 2026-08-19

* Log recipe portions in real grams
* Show real grams for recipe entries in the log
* Fix recipe nutrient scaling in the food log

### 1.4.0: 2026-08-19

* Create and update recipes from ingredients
* List recently logged foods with counts
* Show logging streaks
* Read the account profile
* Re-login only on auth errors, not every failure

### 1.3.0: 2026-08-18

* Return every nutrient eaten, not only tracked ones
* Flag each nutrient as tracked or not
* Add `include_untracked` to keep the old view
* Round summed amounts by significant figures

### 1.2.1: 2026-08-17

* Offer the icon in 48, 96 and 256 px, Ref: [SEP-973](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1040#issuecomment-3967699520)
* Report our own version in `initialize`

### 1.2.0: 2026-08-17

* Set nutrient targets and limits
* Turn tracking of a nutrient on or off
* Name and unit each target in `get_targets`

### 1.1.1: 2026-08-17

* Add step-by-step self-hosting instructions
* Say how each kind of entry is removed
* Hold ruff to the supported Python version

### 1.1.0: 2026-08-17

* Set any of the 94 nutrients on a custom food
* Leave a nutrient unset instead of writing zero
* Reject unknown nutrient names loudly
* Add `list_nutrients` and `retire_custom_food`
* Accept `energy_kj` and `salt_g` from food labels

### 1.0.4: 2026-08-17

* Name the resource in discovery metadata

### 1.0.3: 2026-08-17

* Advertise the icon in the initialize response

### 1.0.2: 2026-08-17

* Serve an icon-bearing page at the root

### 1.0.1: 2026-08-17

* Serve a Cronometer favicon and icon
* Simplify the sign-in page

### 1.0.0: 2026-08-17

* Read the diary with food names and all nutrients
* Add, change and delete food entries
* Add and change notes, measurements and exercise
* Add, change and delete fasts
* Create own foods, copy days, mark days done
* Serve over HTTP behind an OAuth 2.1 login
* Accept a fixed token for Claude Code
* Support two-factor logins via `CRONOMETER_TOTP_SECRET`
* Add installer, service files and nginx site

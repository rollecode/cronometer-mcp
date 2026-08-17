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

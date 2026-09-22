JARVIS -- HOW TO LOG IN
=======================

THE PROBLEM YOU HIT
-------------------
The auth system was built so no password is ever hardcoded in the
source. ensure_owner_seeded() only creates the OWNER account if the
OWNER_PASSWORD environment variable is set. That part was right.

What was wrong was shipping it with no way to set that password. If the
variable was never exported, NO owner account existed at all -- so you,
the owner, had nothing to log in with. A lock with no key. My mistake.


STEP 1 -- CREATE YOUR OWNER ACCOUNT
-----------------------------------
    cd ~/Jarvis_Work
    python3 setup_owner.py

It asks for a password twice (not echoed to the screen) and creates the
owner account. Username defaults to "uk".

Check it worked:
    python3 setup_owner.py --status

Forgot the password later:
    python3 setup_owner.py --reset-password


STEP 2 -- LOG IN
----------------
Open the web UI, use the normal login form:
    username: uk
    password: (what you just set)

NOTE: usernames are stored lowercase. verify_login() lowercases before
its lookup, so an account saved as "UK" could never be matched. That was
a real bug in the first version of this script -- it created the account
successfully and login still failed. Fixed; "UK" and "uk" both work now.


HOW THE THREE LOGINS DIFFER
---------------------------
There is ONE login form and ONE endpoint for everybody. What differs is
the ROLE stored on the account, not how you sign in. That is deliberate:
a separate "/admin" login page tells an attacker exactly where the
privileged door is.

  OWNER     Created only by setup_owner.py. Exactly one exists.
            Cannot be demoted or deleted by anyone, including itself.
            Only a verified owner can grant roles.
            Can run system-level tasks and step-by-step goals.

  CO_OWNER  Near-full authority. Deliberately CANNOT grant roles, so
            nobody can lock you out of your own system.

  ADMIN     Operates and inspects the system. Cannot read users'
            private memory, cannot run system-level tasks, cannot grant
            roles. Admin is a job, not ownership.

  USER      What every signup gets. No promotion needed.

  GUEST     Not logged in. General help only, nothing personal.


MAKING SOMEONE AN ADMIN
-----------------------
They sign up normally through the UI first, then:

    python3 setup_owner.py --promote heramb admin
    python3 setup_owner.py --promote someone co_owner

You cannot promote anyone to owner from here -- there is one owner, and
it is managed with --reset-password.


IF YOU GET LOCKED OUT AGAIN
---------------------------
    python3 setup_owner.py --reset-password

This works directly against data/auth.db and does not need the server to
be running.

"""External market-data feeds (paper research only).

Every feed here is read-only, env-gated, and fail-silent: an outage degrades
to the pre-feed behavior instead of breaking a poller.  Nothing in this
package places orders anywhere -- feeds provide reference prices and
probabilities that the existing paper pipeline consumes.
"""

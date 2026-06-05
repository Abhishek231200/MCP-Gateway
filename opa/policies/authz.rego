package authz

import future.keywords.if
import future.keywords.in

# Role hierarchy: admin > engineer > viewer
# Permission levels: read (open) < write (engineer+) < admin (admin only)

default allow := false
default reason := "Access denied by policy"

# Read: open to all authenticated actors
allow if input.required_permission == "read"

# Write: engineer or admin role required
allow if {
	input.required_permission == "write"
	input.actor_role in {"engineer", "admin"}
}

# Admin: admin role only
allow if {
	input.required_permission == "admin"
	input.actor_role == "admin"
}

# ── Reason strings ────────────────────────────────────────────────────────────

reason := "Read access is permitted for all authenticated actors" if {
	allow
	input.required_permission == "read"
}

reason := sprintf("Write access granted: role '%v' is authorized", [input.actor_role]) if {
	allow
	input.required_permission == "write"
}

reason := sprintf("Admin access granted: role '%v' is authorized", [input.actor_role]) if {
	allow
	input.required_permission == "admin"
}

reason := sprintf(
	"Write access denied: role '%v' requires 'engineer' or 'admin' (actor: %v)",
	[input.actor_role, input.actor],
) if {
	not allow
	input.required_permission == "write"
}

reason := sprintf(
	"Admin access denied: role '%v' requires 'admin' (actor: %v)",
	[input.actor_role, input.actor],
) if {
	not allow
	input.required_permission == "admin"
}

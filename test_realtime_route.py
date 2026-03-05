#!/usr/bin/env python3
"""Test if the /orders/realtime route is registered"""

import sys
import os
os.chdir('C:\\app\\hustle2026\\backend')
sys.path.insert(0, 'C:\\app\\hustle2026\\backend')

from app.main import app

# Print all routes
print("All registered routes:")
for route in app.routes:
    if hasattr(route, 'path') and hasattr(route, 'methods'):
        print(f"{list(route.methods)[0] if route.methods else 'N/A'} {route.path}")

# Check for our specific route
realtime_route = None
for route in app.routes:
    if hasattr(route, 'path') and '/orders/realtime' in route.path:
        realtime_route = route
        break

if realtime_route:
    print(f"\n✓ Found route: {realtime_route.methods} {realtime_route.path}")
else:
    print("\n✗ Route /orders/realtime NOT FOUND")

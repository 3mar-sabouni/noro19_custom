# -*- coding: utf-8 -*-
import math

from odoo import fields


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Compute the great-circle distance between two coordinates.
    """
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_geofence_locations(analytic_account):
    """
    Return a list of (latitude, longitude, radius_km) tuples configured on the analytic account.
    """
    locations = []
    if not analytic_account:
        return locations

    for loc in analytic_account.x_location_ids:
        if loc.latitude and loc.longitude and loc.radius_km and loc.radius_km > 0:
            locations.append((float(loc.latitude), float(loc.longitude), float(loc.radius_km)))
    if locations:
        return locations

    lat_cfg = analytic_account.x_location_lat or 0.0
    lng_cfg = analytic_account.x_location_lng or 0.0
    radius = analytic_account.x_location_radius_km or 0.0
    if radius > 0 and lat_cfg != 0 and lng_cfg != 0:
        locations.append((float(lat_cfg), float(lng_cfg), float(radius)))
    return locations

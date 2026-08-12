setup a pyproject here (use uv).

it's called vps. it should be a python module (and cli).

store env vars in .env (provide a .env.example)

use ovh python module for ovhcloud and hetzner

main API should be:

   import vps

   # Connect to all providers that we provided tokens/keys in env vars as possible
   client = vps.Client()

   # Get a list of plans and prices for all providers we were able to connect to.
   # When orderable_only=True is set, only get the ones that we can order
   prices = client.get_prices(orderable_only=True)

   # Order
   client.create(name, server_type=server_type_instance, image=Image("ubuntu-24.04"), location="nbg1", user_data="#!/bin/bash ...")
   
get_prices() should return list of ServerType and they should have at least: provider (ovhcloud, hetzner, etc), name, cores, memory, disk, prices
prices should be a Price and have at least: location, hourly, monthly

standardize ServerType and Price for all providers

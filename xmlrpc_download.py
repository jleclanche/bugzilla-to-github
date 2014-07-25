#!/usr/bin/env python
"""
Connect to a bugzilla xml-rpc.cgi and download all the things.
This exports products, bugs, comments and bug history to a "bugzilla.json"
output file which can in turn be used to quickly import things to a different
format.
"""

import json
import sys
import xmlrpc.client


# Edit these to your liking or in local_settings.py

# Highest bug id in Bugzilla. Any bug with a higher id will not be imported.
MAX_BUG_ID = 10000

# Export output file
XMLRPC_EXPORT_FILE = "bugzilla.json"

# List of bugs that will not be exported
XMLRPC_BLACKLIST = []


try:
	from local_settings import *
except ImportError:
	pass


class RPCEncoder(json.JSONEncoder):
	def default(self, o):
		if isinstance(o, xmlrpc.client.DateTime):
			return o.value
		raise NotImplementedError


def main():
	if len(sys.argv) < 2:
		sys.stderr.write("Usage: %s [URL TO XML-RPC]\n" % (sys.argv[0]))
		exit(1)

	emails = set()

	print("Connecting to %r" % (sys.argv[1]))
	bugzilla = xmlrpc.client.ServerProxy(sys.argv[1])

	print("Exporting products")
	_products = bugzilla.Product.get(bugzilla.Product.get_selectable_products())["products"]
	products = {product["name"]: product for product in _products}

	print("Exporting bugs")
	valid_ids = filter(lambda i: i not in BLACKLIST, range(1, MAX_BUG_ID))
	bugs = bugzilla.Bug.get({"ids": list(valid_ids), "permissive": True})["bugs"]
	valid_ids = [k["id"] for k in bugs]

	print("Exporting bug history")
	history = bugzilla.Bug.history({"ids": valid_ids})["bugs"]

	print("Exporting comments")
	_comments = bugzilla.Bug.comments({"ids": valid_ids})["bugs"]
	# god damn it bugzilla
	comments = {int(id): _comments[id] for id in _comments}

	for histitem, bug in zip(history, bugs):
		assert histitem["id"] == bug["id"]
		bug["history"] = histitem["history"]

	# turn bugs into a dict
	bugs = {int(bug["id"]): bug for bug in bugs}

	for id, comments in comments.items():
		comments = comments["comments"]
		for comment in comments:
			# Add to the list of users we want to export
			emails.add(comment["author"])
		bugs[id]["comments"] = comments

	# now move the bugs dict to the products
	for product in products.values():
		product["bugs"] = {}

	for id, bug in bugs.items():
		products[bug["product"]]["bugs"][id] = bug

	json_out = {"products": products}

	print("Exporting all users")
	users = bugzilla.User.get({"names": list(emails)})["users"]
	json_out["users"] = {user["name"]: user["real_name"] for user in users}

	with open(EXPORT_FILE, "w") as f:
		f.write(json.dumps(json_out, cls=RPCEncoder))


if __name__ == "__main__":
	main()

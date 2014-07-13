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


# XXX Edit this to your liking
MAX_BUG_ID = 3210
EXPORT_FILE = "bugzilla.json"
BLACKLIST = [489, 3188]


class RPCEncoder(json.JSONEncoder):
	def default(self, o):
		if isinstance(o, xmlrpc.client.DateTime):
			return o.value
		raise NotImplementedError


def main():
	if len(sys.argv) < 2:
		sys.stderr.write("Usage: %s [URL TO XML-RPC]\n" % (sys.argv[0]))
		exit(1)

	print("Connecting to %r" % (sys.argv[1]))
	bugzilla = xmlrpc.client.ServerProxy(sys.argv[1])

	print("Exporting products")
	products = bugzilla.Product.get(bugzilla.Product.get_selectable_products())["products"]

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
	bugs = {bug["id"]: bug for bug in bugs}

	for id in comments:
		bugs[id]["comments"] = comments[id]["comments"]

	with open(EXPORT_FILE, "w") as f:
		f.write(json.dumps(bugs, cls=RPCEncoder))


if __name__ == "__main__":
	main()
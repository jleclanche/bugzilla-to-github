#!/usr/bin/env python

import json
import os
import re


__version__ = "0.1"

# Optional: Add bugzilla-to-github mapping here.
GITHUB_MAPPING = {
	# "email": "github_username"
}

EXPORT_DIRECTORY = "export/"
BUGZILLA_JSON = "bugzilla.json"
DEFAULT_MILESTONE_USER = ""
COMMENT_RE = re.compile(r"comment #(\d+)")
COMMENT_REPLY_RE = re.compile(r"\(In reply to (.+) from comment #(\d+)\)" + "\n")
CREATED_ATTACHMENT_RE = re.compile(r"Created attachment (\d+)" + "\n")
CREATED_ATTACHMENT_SUB = r"Created [attachment \1](%s)" + "\n\n"
ATTACHMENT_URL = "http://bugs.example.com/attachment.cgi?id=%(attachment_id)i"

try:
	from local_settings import *
except ImportError:
	pass


class GithubEncoder(json.JSONEncoder):
	def default(self, o):
		if hasattr(o, "to_github"):
			return o.to_github()
		raise NotImplementedError(o)


def write_json(path, obj):
	dirname = os.path.dirname(path)
	if not os.path.exists(dirname):
		os.makedirs(dirname)

	with open(path, "w") as f:
		print("Writing %r..." % (path))
		json.dump(obj, f, cls=GithubEncoder)


class User(object):
	def __init__(self, email):
		self.email = email
		self.name = ""

	def __bool__(self):
		return self.email != NOBODY_EMAIL

	def __repr__(self):
		return "<%s - %s>" % (self.email, self.name)

	def __str__(self):
		github = self.github_username()
		if github:
			return "@" + github
		return self.name or self.email

	def __hash__(self):
		return self.email.__hash__()

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return self.email == other.email
		return False

	def github_username(self):
		return GITHUB_MAPPING.get(self.email)

	def to_github(self):
		if not self:
			return None
		gh_username = self.github_username()
		if gh_username:
			return {"username": gh_username}
		return {"email": self.email}


_MILESTONES = {}
class Milestone(object):
	@classmethod
	def from_bugzilla_xmlrpc(cls, milestone):
		obj = cls()
		obj.id = milestone["id"]
		obj.is_open = milestone["is_active"]
		obj.title = milestone["name"]
		obj.product = milestone["product"]
		if not DEFAULT_MILESTONE_USER:
			raise RuntimeError("DEFAULT_MILESTONE_USER needs to be set")
		obj.creator = User(DEFAULT_MILESTONE_USER)
		obj.created_at = None # We don't have that.
		obj.due_on = None # We don't have that either.
		obj.description = "" # Nor that.
		return obj

	def to_github(self):
		return {
			"number": self.id,
			"state": "open" if self.is_open else "closed",
			"title": self.title,
			"description": self.description,
			"creator": self.creator,
			"created_at": self.created_at,
			"due_on": self.due_on,
		}


class Comment(object):
	@classmethod
	def from_bugzilla_xmlrpc(cls, comment):
		obj = cls()
		obj.user = User(comment["author"])
		obj.created_at = comment["creation_time"]
		# obj.updated_at = comment["creation_time"] # Bugzilla does not allow comment editing
		obj.updated_at = None
		obj.body = comment["text"]
		obj.attachment = comment.get("attachment_id")
		if obj.attachment:
			repl = CREATED_ATTACHMENT_SUB % (ATTACHMENT_URL % {"attachment_id": obj.attachment})
			obj.body = re.sub(CREATED_ATTACHMENT_RE, repl, obj.body)
		return obj

	def to_github(self):
		return {
			"user": self.user,
			"body": self.body,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}


# TODO We may need to do some preprocessing on the text.
# For example, we don't want the "(In reply to comment #123)" to link to issues.
# sre = COMMENT_RE.search(text, re.IGNORECASE)
# if sre:
# 	print(re.sub(COMMENT_RE, r"... \1 ...", text))

class Bug(object):
	@classmethod
	def from_bugzilla_xmlrpc(cls, bug):
		obj = cls()
		obj.id = bug["id"]
		obj.title = bug["summary"]
		obj.created_at = bug["creation_time"]
		obj.updated_at = bug["last_change_time"]
		obj.user = User(bug["creator"])
		obj.users = [User(u) for u in bug["cc"]] # TODO how do I github this?
		obj.assignee = User(bug["assigned_to"])
		obj.milestone = _MILESTONES[bug["target_milestone"]]
		obj.is_open = bug["is_open"]
		obj.product = bug["product"]
		obj.component = bug["component"]

		# unused fields
		obj.dupe_of = bug.get("dupe_of")
		obj.is_confirmed = bug["is_confirmed"]
		obj.version = bug["version"]

		# process history for closed_at
		obj.closed_at = None
		for item in bug["history"]:
			for change in item["changes"]:
				if change["field_name"] == "status":
					if change["added"] == "RESOLVED":
						# change["who"] closed this on change["when"]
						obj.closed_at = item["when"]
					elif change["added"] == "REOPENED":
						# change["who"] reopened this on change["when"]
						pass

		obj.comments = []
		for i, comment in enumerate(bug["comments"]):
			if i == 0:
				obj.body = comment["text"]
			else:
				obj.comments.append(Comment.from_bugzilla_xmlrpc(comment))

		return obj

	def get_labels(self):
		labels = []
		if self.component in COMPONENT_MAPPING.get(self.product, {}):
			labels.append(COMPONENT_MAPPING[self.product][self.component])
		return labels

	def to_github(self):
		return {
			"number": self.id,
			"title": self.title,
			"body": self.body,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
			"closed_at": self.closed_at,
			"user": self.user,
			"assignee": self.assignee,
			"milestone": self.milestone and self.milestone.id,
			"labels": self.get_labels(),
			"state": "open" if self.is_open else "closed",
		}


def process_milestone(milestone):
	if milestone["name"] == "---":
		# stupid bugzilla ...
		_MILESTONES["---"] = None
		return
	milestone = Milestone.from_bugzilla_xmlrpc(milestone)
	_MILESTONES[milestone.title] = milestone
	path = os.path.join(EXPORT_DIRECTORY, milestone.product, "milestones/%i.json" % (milestone.id))
	write_json(path, milestone)


def process_bug(bug):
	bug = Bug.from_bugzilla_xmlrpc(bug)
	path = os.path.join(EXPORT_DIRECTORY, bug.product, "issues/%i.json" % (bug.id))
	write_json(path, bug)
	path = os.path.join(EXPORT_DIRECTORY, bug.product, "issues/%i.comments.json" % (bug.id))
	write_json(path, bug.comments)


def main():
	ret = {}

	with open(BUGZILLA_JSON, "r") as f:
		products = json.load(f)

	for product_name, product in products.items():
		print("Processing %r (%i bugs)" % (product_name, len(product["bugs"])))
		for milestone in product["milestones"]:
			milestone["product"] = product_name
			process_milestone(milestone)

		for id in sorted(product["bugs"].keys()):
			process_bug(product["bugs"][id])


if __name__ == "__main__":
	main()

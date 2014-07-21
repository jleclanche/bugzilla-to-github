#!/usr/bin/env python

import json
import os
import re
from datetime import datetime


__version__ = "0.1"

# Optional: Add bugzilla-to-github mapping here.
GITHUB_MAPPING = {
	# "email": "github_username"
}

EXPORT_DIRECTORY = "export/"
BUGZILLA_JSON = "bugzilla.json"
DEFAULT_MILESTONE_USER = ""
COMMENT_RE = re.compile(r"comment #(\d+)")
COMMENT_SUB = r"```BZ-IMPORT::comment #\1```"
COMMENT_REPLY_RE = re.compile(r"\(In reply to (.+) from comment #(\d+)\)" + "\n")
BUG_NO_HASH_RE = re.compile(r"bug (\d+)")
BUG_NO_HASH_SUB = r"bug #\1"
OP_VERSION_METADATA = "Version: %(version)s\n\n%(body)s"
VERSION_BLACKLIST = ["unspecified", "master"]
CREATED_ATTACHMENT_RE = re.compile(r"Created attachment (\d+)" + "\n")
CREATED_ATTACHMENT_SUB = r"Created [attachment \1](%s)" + "\n\n"
ATTACHMENT_URL = "http://bugs.example.com/attachment.cgi?id=%(attachment_id)i"
MISSING_MAPPING_DISCLAIMER = "Originally posted by %(user)s:\n\n%(text)s"
USER_DELETE_COMMENTS = "nobody@github.local"
CCS_COMMENT_PLACEHOLDER = "This comment is a placeholder to subscribe all extra CCs to this issue. It should be deleted.\n\nCC: %s"
DISPLAY_USER_EMAILS = False

try:
	from local_settings import *
except ImportError:
	pass


class GithubEncoder(json.JSONEncoder):
	def default(self, o):
		if isinstance(o, datetime):
			return o.isoformat()
		elif hasattr(o, "to_github"):
			return o.to_github()
		raise NotImplementedError(o)


def write_json(path, obj):
	dirname = os.path.dirname(path)
	if not os.path.exists(dirname):
		os.makedirs(dirname)

	with open(path, "w") as f:
		print("Writing %r..." % (path))
		json.dump(obj, f, cls=GithubEncoder)


_USERS = {}
class User(object):
	def __init__(self, email):
		self.email = email
		self.name = _USERS.get(email)

	def __bool__(self):
		return self.email != NOBODY_EMAIL

	def __repr__(self):
		return "<%s - %s>" % (self.email, self.name)

	def __str__(self):
		github = self.github_username()
		if github:
			return "@" + github
		if DISPLAY_USER_EMAILS:
			return self.name or self.email
		return self.name or "(unknown user)"

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
	def __init__(self):
		self.created_at = datetime.now()
		# Bugzilla does not allow comment editing
		self.updated_at = None
		self.body = ""

	@classmethod
	def from_bugzilla_xmlrpc(cls, comment):
		obj = cls()
		obj.user = User(comment["author"])
		obj.created_at = comment["creation_time"]
		obj.body = comment["text"]
		obj.attachment = comment.get("attachment_id")
		if obj.attachment:
			repl = CREATED_ATTACHMENT_SUB % (ATTACHMENT_URL % {"attachment_id": obj.attachment})
			obj.body = re.sub(CREATED_ATTACHMENT_RE, repl, obj.body)

		obj.body = re.sub(COMMENT_RE, COMMENT_SUB, obj.body)
		obj.body = re.sub(BUG_NO_HASH_RE, BUG_NO_HASH_SUB, obj.body)
		if not obj.user.github_username():
			obj.body = MISSING_MAPPING_DISCLAIMER % {"user": obj.user, "text": obj.body}
		return obj

	def to_github(self):
		return {
			"user": self.user,
			"body": self.body,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}


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
		obj.version = bug["version"]

		# unused fields
		obj.dupe_of = bug.get("dupe_of")
		obj.is_confirmed = bug["is_confirmed"]

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
		obj.comment_authors = set()
		for comment in bug["comments"]:
			comment = Comment.from_bugzilla_xmlrpc(comment)
			obj.comments.append(comment)
			obj.comment_authors.add(comment.user)

		# The body of the bug is comment #0
		obj.body = obj.comments.pop(0).body

		# Add version info to the body
		if obj.version not in VERSION_BLACKLIST:
			obj.body = OP_VERSION_METADATA % {"version": obj.version, "body": obj.body}

		# process extra CCs (not in comment authors)
		extra_ccs = [user for user in obj.users if user not in obj.comment_authors and user.github_username()]
		if extra_ccs:
			ccs_comment = Comment()
			ccs_comment.user = User(USER_DELETE_COMMENTS)
			ccs_comment.body = CCS_COMMENT_PLACEHOLDER % " ".join(str(user) for user in extra_ccs)
			obj.comments.append(ccs_comment)

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
		data = json.load(f)

	global _USERS, _MILESTONES
	_USERS = data["users"]
	products = data["products"]

	for product_name, product in products.items():
		print("Processing %r (%i bugs)" % (product_name, len(product["bugs"])))
		for milestone in product["milestones"]:
			milestone["product"] = product_name
			process_milestone(milestone)

		for id in sorted(product["bugs"].keys()):
			process_bug(product["bugs"][id])


if __name__ == "__main__":
	main()

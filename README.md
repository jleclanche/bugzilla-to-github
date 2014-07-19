### Bugzilla to Github migration scripts

This is a toolset to help Bugzilla to Github migrations.

./xmlrpc_download.py will download all relevant data from a Bugzilla
installation through its XML-RPC interface into a `bugzilla.json` file.

./github_internal.py will create a set of exportable files in Github's internal
format to the `export/` directory.
Note that post-processing is still needed for the following:

 - Comment linking
 - CCs cleanup
 - Milestones cleanup
 - Possibly more

All code is licensed as MIT. See LICENSE file for more details.

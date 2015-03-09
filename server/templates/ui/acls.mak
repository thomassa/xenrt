<!doctype html>
<html lang=''>
<head>
    <title>XenRT: ACL Management</title>

${commonhead | n}
    <script>
$(function() {
    $( "#newacl" ).click(function() {
    }); 
    $( "#editacl" ).click(function() {
        window.location = "/xenrt/ui/acl?" + $( "#aclid" ).val();
    }); 
    $( "#deleteacl" ).click(function() {
        var aclname = $( "#aclid option:selected" ).text();
        if (!window.confirm("Are you sure you want to delete the ACL '" + aclname + "'?")) {
            return;
        }
        $( "#overlay" ).show();
        $( "#loading" ).show();
        $.ajaxSetup( { "async": false } );
        var keydelete = "/xenrt/api/v2/acl/" + $( "#aclid" ).val();
        $.ajax({
            url: keydelete,
            type: 'DELETE',
            async: false,
            success: function(data) {
                var out = "<p>ACL '" + aclname + "' deleted successfully.</p>";
                $( out ).appendTo( "#deletestatus" );
                populateAcls();
            },
            error: function(jqXHR, textStatus, errorThrown) {
                try {
                    var response = $.parseJSON(jqXHR.responseText);
                    alert("Unable to delete ACL: " + response.reason);
                }
                catch(e)
                {
                    alert("Unable to delete ACL - " + textStatus + " - " + errorThrown);
                }
            }
        });
        $( "#overlay" ).hide();
        $( "#loading" ).hide();

    });
    function populateAcls() {
        $.getJSON ("/xenrt/api/v2/acls", {"owner": "me"})
            .done(function(data) {
                $( "#aclid" ).find('option').remove();
                $.each(data, function(aclid, acldata) {
                    $(" #aclid" ).append("<option value=" + aclid + ">" + acldata.name + "</option>");
                });
            });
    }
    $( document ).ready(populateAcls);
});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">

<div id="aclcontrols">
<h2>Manage ACLs</h2>
<h3>New ACL</h3>
<p>
Name: <input id="newacl" type="text" class="ui-state-default ui-corner-all" /><br />
<button id="newacl" class="ui-state-default ui-corner-all">Create</button>
</p>
<div id="deletestatus"></div>
<h3>Existing ACLs</h3>
<p>
ACL: <select id="aclid" class="ui-state-default ui-corner-all"></select><br />
<button id="editacl" class="ui-state-default ui-corner-all">Edit</button> <button id="deleteacl" class="ui-state-default ui-corner-all">Delete</button>
</p>
</div>

</div>
</body>
</html>

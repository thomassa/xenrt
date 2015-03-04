<!doctype html>
<html lang=''>
<head>
   <title>XenRT: Machines</title>

${commonhead | n}
    <script>
$(function() {

    var curRequest = null;

    function search(searchtext, user) {
        $('#searchbutton').prop('disabled', true);
        $('#mybutton').prop('disabled', true);
        $( "#overlay" ).show();
        $( "#loading" ).show();
        if (curRequest) {
            curRequest.abort();
        }
        var params = null;
        if (user) {
            limit = "0"
            params = {"user": "${'${user}'}", "limit" : "0"}
        }
        else {
            params = {"search": searchtext, "limit": "25"}
        }
        $.ajaxSetup( { "async": false } );
        var machinesearch = "/xenrt/api/v2/machines"
        curRequest = $.getJSON(machinesearch, params)
            .done(function(data) {
                curRequest = null;
                var out = searchHTML(data)
                $("#results").empty();
                $( out ).appendTo("#results");
            });
        $( "#overlay" ).hide();
        $( "#loading" ).hide();
        $('#searchbutton').prop('disabled', false);
        $('#mybutton').prop('disabled', false);
    }

    function searchHTML(data) {
        var out = ""
        for (var key in data) {
            out += "<div class=\"ui-widget-content ui-corner-all\">";

            out += key;
            out += ": <a href=\"/xenrt/ui/machine?" + escape(key) + "\">Manage</a>";

            out += "</div>";
        }
        return out
    }

    $( "#searchbutton" ).click(function() {
        var machinesearch = $( "#searchbox" ).val()
        search(machinesearch, false);
    });

    $( "#mybutton").click(function() {
        search(null, true); 
    });

    $("#searchbox").keyup(function(event){
        if(event.keyCode == 13){
            $("#searchbutton").click();
        }
        else {
            // These lines allow real time searching, but also put a greater load on the server. Decide later whether we can enable this
            //$.ajaxSetup( { "async": true } );
            //var machinesearch = $( "#searchbox" ).val()
            //search(machinesearch);
        }
    });

});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">
<h2>Find machine</h2>
<p>
<input id="searchbox" type="text" class="ui-state-default ui-corner-all">
<button id="searchbutton" class="ui-state-default ui-corner-all">Search</button>
<button id="mybutton" class="ui-state-default ui-corner-all">Get my machines</button></p>
<div id="results"></div>
</p>
</div>
</body>
</html>
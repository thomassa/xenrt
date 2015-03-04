<!doctype html>
<html lang=''>
<head>
   <title>XenRT: Machine</title>

${commonhead | n}
    <script>
$(function() {
    var machine = unescape(self.location.search.substring(1));

    var heading = "<h2>Manage " + machine + "</h2>";

    $( heading ).appendTo("#heading");

    document.title = "XenRT: Machine " + machine;

    function leaseUntilText(ts) {
        if (ts == 1893456000) {
            return "forever"
        }
        else {
            var d = new Date(ts * 1000)
            return "until " + d.toLocaleString()
        }
    }

    function getMachine(machine) {
        $.ajaxSetup( { "async": false } );
        $.getJSON("/xenrt/api/v2/machine/" + machine)
            .done(function(data) {
                var out = ""
                out += "<h3>Machine lease</h3>"
                if (data['leasecurrentuser']) {
                    out += "<div>"
                    out += "Leased to you " +  leaseUntilText(data['leaseto']);
                    out += " <button id=\"returnbutton\" class=\"ui-state-default ui-corner-all\">Return machine</button>"
                    out += "<h3>Power control</h3>"
                    out += "<div>Operation: <select class=\"ui-state-default ui-corner-all\" id=\"powerop\">"
                    out += "<option value=\"on\">Power on</option>"
                    out += "<option value=\"off\">Power off</option>"
                    out += "<option value=\"reboot\">Power cycle</option>"
                    out += "<option value=\"nmi\">Send NMI</option>"
                    out += "</select>"
                    out += " <button id=\"powerbutton\" class=\"ui-state-default ui-corner-all\">Go</button></div>"
                    out += "<div id=\"output\"></div>"
                    out += "<h3>Serial console</h3>"
                    out += "<div>Unix: <span style=\"font-family:monospace\">ssh -t cons@" + data['ctrladdr'] + " " + machine + "</span> (password <span style=\"font-family:monospace\">console</span>)</div>";
                    out += "<div>Windows: <span style=\"font-family:monospace\">echo " + machine + " > %TEMP%\\xenrt-puttycmd & putty.exe -t cons@" + data['ctrladdr'] + " -pw console -m %TEMP%\\xenrt-puttycmd</span> (requires PuTTY on %PATH%)</div>";
                    out += "</div>"
                }
                else {
                    if (data['leaseuser']) {
                        var d = new Date(data['leaseto'] * 1000)
                        out += "<div>Machine is borrowed by " + data['leaseuser'] + " " + leaseUntilText(data['leaseto']) + "</div>"
                    }
                    else{
                        out += "<div>Lease for: "
                        out += "<input type=\"text\" id=\"duration\" class=\"ui-state-default ui-corner-all\">"
                        out += " <select id=\"durationunit\" class=\"ui-state-default ui-corner-all\">"
                        out += "<option value=\"hours\">Hours</option>"
                        out += "<option value=\"days\">Days</option>"
                        out += "<option value=\"forever\">Forever</option>"
                        out += "</select>"
                        out += "<br>Reason: <input type=\"text\" id=\"reason\" class=\"ui-state-default ui-corner-all\">"
                        out += "<br><button id=\"leasebutton\" class=\"ui-state-default ui-corner-all\">Lease</button></div>"
                    }
                }
                $("#machine").empty()
                $(out).appendTo("#machine");
                setupHandlers()
            });

    }
    
    getMachine(machine)

    function setupHandlers() {

        $( "#powerbutton" ).click(function() {
            $('#powerbutton').prop('disabled', true);
            $( "#overlay" ).show();
            $( "#loading" ).show();
            $.ajaxSetup( { "async": false } );
            $.post("/xenrt/api/v2/machine/" + machine + "/power",
                    JSON.stringify({"operation": $("#powerop").val()}),
                    function(response) {
                        out = "<h3>Output</h3><pre>\n"
                        out += response['output']
                        out += "</pre>";
                        $("#output").empty();
                        $(out).appendTo("#output");
                    }, "json");
            $( "#overlay" ).hide();
            $( "#loading" ).hide();
            $('#powerbutton').prop('disabled', false);
        });

        $( "#returnbutton" ).click(function() {
            $('#returnbutton').prop('disabled', true);
            $( "#overlay" ).show();
            $( "#loading" ).show();
            
            $.ajaxSetup( { "async": false } );
            $.ajax({
                url: "/xenrt/api/v2/machine/" + machine + "/lease",
                type: "DELETE",
                dataType: "json",
                error: function(jqXHR, textStatus, errorThrown) {
                    alert("Error returning machine: " + textStatus + " " + errorThrown)
                }
            });

            getMachine(machine);
            $( "#overlay" ).hide();
            $( "#loading" ).hide();
        });

        $( "#leasebutton" ).click(function() {

            unit = $("#durationunit").val()
            dur = $("#duration").val()

            var duration = null;

            if (unit == "forever") {
                duration = 0;
            }
            else if (unit == "days") {
                duration = parseInt(dur) * 24;
            }
            else if (unit == "hours") {
                duration = parseInt(dur)
            }

            $('#leasebutton').prop('disabled', true);
            $( "#overlay" ).show();
            $( "#loading" ).show();
           
            $.ajaxSetup( { "async": false } );
            $.ajax({
                url: "/xenrt/api/v2/machine/" + machine + "/lease",
                data: JSON.stringify({"duration": duration, "reason": $("#reason").val()}),
                type: "POST",
                dataType: "json",
                error: function(jqXHR, textStatus, errorThrown) {
                    alert("Error leasing machine: " + textStatus + " " + errorThrown)
                }
            });
            
            getMachine(machine);
            $( "#overlay" ).hide();
            $( "#loading" ).hide();
        });
    }
});
    </script>

</head>
<body>

${commonbody | n}
<div id="mainbody">
<div id="heading"></div>
<div id="machine"></div>

</div>
</body>
</html>
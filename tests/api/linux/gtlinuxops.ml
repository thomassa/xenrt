
let rec read ic cur = 
  try
    let line = input_line ic in
    read ic (line::cur) 
  with
    _ -> List.rev cur

let shutdown timeout =
  (* Timeout measured in mins! ignore timeout then :) *)
  let ic = Unix.open_process_in "poweroff" in
  Gtmessages.CmdResult ""

let reboot timeout =
  (* Timeout measured in mins! ignore timeout then :) *)
  let ic = Unix.open_process_in "reboot" in
  Gtmessages.CmdResult ""

let crash () =
  ignore(Sys.command "echo 1 > /proc/sys/kernel/panic_on_oops";
	 Sys.command "dd if=/dev/zero of=/dev/mem");
  Gtmessages.CmdResult ""

let checkcds devices =
  let is_pv = try ignore(Unix.stat "/proc/xen"); true with _ -> false in
  let devmap = 
    if is_pv then ["2","xvdc";"3","xvdd"] else ["2","hdc";"3","hdd"]
  in  
  let results = List.map (fun dev -> 
    let ldevice = List.assoc dev devmap in
    Sys.command ("mkdir -p /mnt/cdrom0");
    Sys.command ("mount /dev/"^ldevice^" /mnt/cdrom0");
    let ic = Unix.open_process_in "ls /mnt/cdrom0" in
    let result = read ic [] in
    Sys.command "umount /mnt/cdrom0";
    dev ^ ":\n\n" ^ (String.concat "\n" result)) devices in
  Gtmessages.CmdResult (String.concat "\n" results)

let checkdisks devices =
  let results = List.map (fun dev -> 
    let ldevice = dev in
    let ic = Unix.open_process_in ("fdisk /dev/"^ldevice) in
    let result = read ic [] in
    String.concat "\n" result) devices in
  Gtmessages.CmdResult (String.concat "\n" results)

let setuptestdisk device = (* Device is in this case a full sda or hda or whatever *)
  let (ic,oc)=Unix.open_process ("sfdisk /dev/"^device) in
  Printf.fprintf oc ",,c;\n";
  flush_all ();
  close_out oc;
  ignore(read ic []);
  Sys.command ("mkdosfs /dev/"^device^"1");
  Sys.command "mkdir -p /mnt/disk";
  Sys.command ("mount /dev/"^device^"1 /mnt/disk");
  Sys.command ("touch /mnt/disk/testing");
  Sys.command ("umount /mnt/disk");
  Gtmessages.CmdResult "OK"
  
let checkmountdisks devices =
  (* Don't know whether we're pv (sdx) or hvm (hdx), so try both *)
  let mapfn dev =
    let ldevice = dev in
    Sys.command "mkdir -p /mnt/disk";
    Sys.command (Printf.sprintf "mount /dev/%s /mnt/disk" ldevice);
    let ic = Unix.open_process_in "ls /mnt/disk" in
    let result = read ic [] in
    Sys.command "umount /mnt/disk";
    String.concat "\n" result in
  let results = List.map mapfn devices in
  Gtmessages.CmdResult (String.concat "\n" results)

let checkvifs device =
  let map = [("0","eth0");("1","eth1");("2","eth2")] in
  let hostdevice = List.assoc device map in
  let ic = Unix.open_process_in ("ifconfig "^hostdevice) in
  let lines = read ic [] in
  Gtmessages.CmdResult (List.hd lines)

    

  


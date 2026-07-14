' Server base URL — the __SERVER_BASE__ placeholder is rewritten by
' scripts/roku-deploy.ps1 at packaging time (e.g. http://192.168.1.50).
function GetServerBase() as String
    return "__SERVER_BASE__"
end function

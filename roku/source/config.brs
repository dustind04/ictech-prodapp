' Server base URL. scripts/roku-deploy.ps1 rewrites the quoted token
' below at packaging time with the backstage PC address (plain ASCII
' comment on purpose: the file is re-encoded during packaging).
function GetServerBase() as String
    return "__SERVER_BASE__"
end function

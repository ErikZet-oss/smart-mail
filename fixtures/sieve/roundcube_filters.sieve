require ["fileinto","reject","vacation","envelope","imapflags","relational","comparator-i;ascii-numeric","regex","date"];
# rule:[Dodávatelia Acme]
if anyof (address :contains ["From"] "objednavky@acme-parts.test", address :contains ["From"] "@acme-parts.test")
{
	fileinto "Dodávatelia";
	stop;
}
# rule:[Faktúry - vypnuté]
# disabled
# if allof (header :contains "Subject" "faktura")
# {
#	fileinto "Faktúry";
#	stop;
# }
# rule:[Od kuriera]
if address :is "From" "dispecing@ship-test.example"
{
	fileinto "Kurier";
	stop;
}
# rule:[Regex - len Roundcube]
if header :regex "Subject" "^URGENT-"
{
	fileinto "INBOX";
	stop;
}

from optparse import OptionParser
import sys
import msc_utils
import getpass
from msc_utils import *

d=False # debug_mode

def main():
    parser = OptionParser("usage: %prog [options]")
    parser.add_option("-m", "--transaction-method", dest="tx_method", default="multisig", type="string",
                        help="basic or multisig")
    parser.add_option("-c", "--currency-id", dest="currency_id", default=2, type="int",
                        help="1 for Mastercoin, 2 for Test Mastercoin")
    parser.add_option("-a", "--amount", dest="amount", default='1', type="string",
                        help="amount of coins")
    parser.add_option("-x", "--fee", dest="fee", default='0.0001', type="string",
                        help="fee for transaction")
    parser.add_option("-r", "--recipient", dest="recipient_address", default='17RVTF3vJzsuaGh7a94DFkg4msJ7FcBYgX', type="string",
                        help="recipient address")
    parser.add_option("-f", "--from", dest="from_address", default='UNKNOWN', type="string",
                        help="from address or pubkey")
    parser.add_option("-p", "--private-key", dest="priv_key", default=None, type="string",
                        help="private key for signing the tx (overrides from address)")
    parser.add_option("-k", "--key-prompt", action="store_true",dest='key_prompt', default=False,
                        help="prompt for hidden private key for signing the tx (overrides from address)")
    parser.add_option("-s", "--send-tx", dest="host_port", default=None, type="string",
                        help="transmit tx to specific bitcoin node HOST:PORT")
    parser.add_option("-b", "--broadcast-tx", action="store_true", dest="broadcast", default=False,
                        help="broadcast tx to bitcoin network")
    parser.add_option("-d", "--debug", action="store_true", dest='debug_mode', default=False,
                        help="turn debug mode on")

    (options, args) = parser.parse_args()
    tx_method=options.tx_method
    currency_id=options.currency_id
    formatted_currency_id='{:08x}'.format(currency_id)
    amount=int(float(options.amount)*100000000+0.5)
    fee=int(float(options.fee)*100000000)
    recipient_address=options.recipient_address
    from_address=options.from_address
    priv_key=options.priv_key
    key_prompt=options.key_prompt
    host_port=options.host_port
    broadcast=options.broadcast
    d=options.debug_mode
    tx_type=0 # only simple send is supported

    info("Using settings: "+str(options))

    if key_prompt:
        priv_key = getpass.getpass("Enter your private key:")
        info('Private key was entered')

    if priv_key != None:
        # calculate from address and pubkey
        from_address_pub=pubkey(priv_key)
        if from_address_pub == None:
            error('Invalid private key')
        from_address=get_addr_from_key(priv_key)
    else:
        # check if address or pubkey was given as from address
        if from_address.startswith('04'): # a pubkey was given
            from_address_pub=from_address
            from_address=get_addr_from_key(from_address)
        else: # address was given
            from_address_pub=get_pubkey_with_instructions(from_address)

    # set change address to from address
    change_address_pub=from_address_pub
    changeAddress=from_address

    recipientBytes = b58decode(recipient_address, 25);
    recipientSequenceNum = ord(recipientBytes[1])
    dataSequenceNum = recipientSequenceNum - 1
    if dataSequenceNum < 0:
        dataSequenceNum = dataSequenceNum + 256
    dataHex = '{:02x}'.format(0) + '{:02x}'.format(dataSequenceNum) + \
            '{:08x}'.format(tx_type) + '{:08x}'.format(currency_id) + \
            '{:016x}'.format(amount) + '{:06x}'.format(0)
    dataBytes = dataHex.decode('hex_codec')
    dataAddress = hash_160_to_bc_address(dataBytes[1:21])

    # get utxo required for the tx

    if tx_method == "basic":
        required_value=3*dust_limit
    else:
        # multisig
        required_value=2*dust_limit

    utxo_all=get_utxo(from_address, required_value+fee)
    utxo_split=utxo_all.split()
    inputs_number=len(utxo_split)/12
    inputs=[]
    inputs_total_value=0

    for i in range(inputs_number):
        inputs.append(utxo_split[i*12+3])
        try:
            inputs_total_value += int(utxo_split[i*12+7])
        except ValueError:
            error('error parsing value from '+utxo_split[i*12+7])

    inputs_outputs='/dev/stdout'
    for i in inputs:
        inputs_outputs+=' -i '+i
    if tx_method == "basic":
        # simple send - basic
        change_value=inputs_total_value-3*dust_limit-fee
        if change_value < 0:
            error ('negative change value')
        inputs_outputs+=' -o '+exodus_address+':'+str(dust_limit) + \
                        ' -o '+recipient_address+':'+str(dust_limit) + \
                        ' -o '+dataAddress+':'+str(dust_limit) + \
                        ' -o '+changeAddress+':'+str(change_value)
    else:
        # simple send - multisig
        # embedding rawscript "1 [ change_address_pub recepientHex+dataHex+padding ] 2 checkmultisig"
        recipientHex=recipientBytes.encode('hex_codec')
        padded_recipientHex_and_dataHex=recipientHex+dataHex+''.zfill(130-50-42)
        script_str='1 [ '+change_address_pub+' ] [ '+padded_recipientHex_and_dataHex+' ] 2 checkmultisig'
        debug(d,'change address is '+changeAddress)
        debug(d,'receipent is '+recipient_address)
        debug(d,'total inputs value is '+str(inputs_total_value))
        debug(d,'fee is '+str(fee))
        debug(d,'dust limit is '+str(dust_limit))
        debug(d,'BIP11 script is '+script_str)
        dataScript=rawscript(script_str)
        change_value=inputs_total_value-dust_limit-fee
        if change_value < 0:
            error ('negative change value')
        inputs_outputs+=' -o '+exodus_address+':'+str(dust_limit) + \
                        ' -o '+dataScript+':'+str(change_value)

    tx=mktx(inputs_outputs)
    debug(d,'inputs_outputs are '+inputs_outputs)
    debug(d,'parsed tx is '+str(get_json_tx(tx)))

    currency_str='unknown currency'
    try:
        currency_str=currency_type_dict[formatted_currency_id]
    except KeyError:
        pass

    if priv_key != None:
        signed_tx=sign(tx, priv_key, inputs)
        f=open('signed_tx.tx','w')
        f.write(signed_tx)
        f.close()
        info('validating tx: '+validate_tx('signed_tx.tx'))
        info('SIGNED tx ('+tx_method+') of '+str("{0:.8f}".format(amount/100000000.0))+\
            ' '+currency_str+' to '+ recipient_address+' signed by '+from_address+'\n'+signed_tx)
        parse_test(signed_tx)
        if host_port != None:
            try:
                host=host_port.split(':')[0].strip('\n')
                port=host_port.split(':')[1].strip('\n')
            except IndexError:
                error('cannot parse sendtx address '+host_port)
            info('Please confirm with "yes" to send the signed tx to '+ host +' on port '+port+' [N/y]:')
            if (yesno()):
                send_tx('signed_tx.tx', host, port)
            else:
                info('dry run only (phew ...)')
        else:
            if broadcast == True:
                info('Please confirm with "yes" to broadcast the signed tx [N/y]:')
                if (yesno()):
                    broadcast_tx('signed_tx.tx')
                else:
                    info('dry run only (phew ...)')
            else:
                info('please send using "sx broadcast-tx signed_tx.tx"')
    else:
        info('UNSIGNED tx ('+tx_method+') of '+str("{0:.8f}".format(amount/100000000.0))+\
            ' '+currency_str+' to '+ recipient_address+' ready for signing by '+from_address+'\n'+tx)
        parse_test(tx)
        info('please sign with '+from_address+' and send using "sx sendtx FILENAME [HOST] [PORT]"')

def parse_test(tx, tx_hash='unknown'):
    method=get_tx_method(tx, tx_hash)
    if method == 'multisig_simple':
        info(parse_multisig_simple(tx))
    else:
        if method == 'multisig_long':
            info(parse_multisig_long(tx))
        else:
            if method == 'basic':
                info(parse_simple_basic(tx))
            else:
                error('cannot parse tx with method '+method)

def get_pubkey_with_instructions(addr):
    addrPub=get_pubkey(addr)
    if not addrPub.startswith('04'):
        error(addrPub.strip('\n') + \
            "\nplease supply pubkey of "+addr+" instead of the address\n" + \
            "one option to get the pubkey is run on offline machine echo $PRIVKEY | sx pubkey")
    return addrPub.strip('\n')

def yesno():
    yes = set(['yes','y', 'ye'])
    choice = raw_input().lower()
    if choice in yes:
        return True
    else:
        return False

if __name__ == "__main__":
    main()

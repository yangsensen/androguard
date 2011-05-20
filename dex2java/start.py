import sys
sys.path.append('./')
import androguard
import analysis
import copy
import Instruction
import Util

class This():
    def __init__(self, cls):
        self.cls = cls

    def get_content(self):
        return self

    def set_field(self, field, value):
        if self.cls.fields.get(field) is None:
            Util.log('field %s does not exist. (value : %s).' % (field, value), 'error')
            return
        self.cls.fields[field] = value

    def get_field(self, field):
        res = self.cls.fields.get(field)
        if res is None:
            Util.log('field %s does not exist.' % field, 'error')
        return res

    def get_value(self):
        return 'this'


class Param():
    def __init__(self, name, type):
        self.name = name
        self.type = type

    def get_content(self):
        return self

    def get_value(self):
        return self.name

    def __repr__(self):
        return '%s %s' % (self.type, self.name)


class Register():
    def __init__(self, content, num):
        self.content = content
        self.nbuses = 0
        self.used = False
        self.num = num

    def modify(self, ins):
        if self.used:
            self.dump(ins)
        self.content = ins
        self.nbuses = 0
        self.used = False

    def get_content(self):
        self.nbuses += 1
        if self.nbuses >= 2:
            self.used = True
            Util.log('GET CONTENT -> USED TRUE', 'debug')
        return self.content

    def dump(self, ins):
        Util.log('Register #%d Dump :' % self.num, 'debug')
        Util.log('---------------', 'debug')
        Util.log('Old value :', 'debug')
        Util.log(self.content, 'debug')
        Util.log('-> %s' % self.content.get_value(), 'debug')
        Util.log('-------', 'debug')
        Util.log('New value :', 'debug')
        Util.log(ins, 'debug')
        Util.log('-> %s' % ins.get_value(), 'debug')
        Util.log('---------------', 'debug')

    def __deepcopy__(self, dic=None):
        d = dic.get(self)
        if d is None:
            r = Register(self.content, self.num)
            r.used = self.used
            return r
        return d

    def __str__(self):
        return 'Register number %d :\n\tused : %s\n\tcontent %s\n\t\t %s.' % (\
        self.num, self.used, str(self.content), str(self.content.get_value()))

    def __repr__(self):
        return repr(self.content)

class DvMethod():
    def __init__(self, methanalysis, this):
        self.memory = {}
        self.analysis = methanalysis
        self.method = self.analysis.get_method()
        self.name = self.method.get_name()
        self.lparams = []
        if self.name == '<init>':
            self.name = self.method.get_class_name()[1:-1].split('/')[-1]
        self.basic_blocks = self.analysis.basic_blocks.bb
        code = self.method.get_code()

        access = self.method.get_access()
        self.access = []
        for flag in Util.ACCESS_FLAGS_METHODS:
            if flag & access:
                self.access.append(flag)

        desc = self.method.get_descriptor()
        self.type = Util.get_type(desc.split(')')[-1])
        params = desc.split(')')[0][1:].split()
        if params:
            self.paramsType = [Util.get_type(param) for param in params]
        else:
            self.paramsType = None

        if code is None:
            self.nbregisters = 0
            self.nbparams = 0
            self.this = None
            Util.log('CODE NONE :', self.name, self.method.get_class_name(), 'debug')
        else:
            self.nbregisters = code.registers_size.get_value()
            self.nbparams = code.ins_size.get_value()
            # 0x8 == Static case : this is not passed as a parameter
            if 0x8 in self.access:
                self.this = None
                for i in xrange(0, self.nbparams):
                    num = self.nbregisters - (i + 1)
                    self.memory[num] = Register(Param('param%s' % (i + 1), self.paramsType[i]), num)
                    self.lparams.append(self.memory[num])
            else:
                self.this = self.nbregisters - self.nbparams
#                print 'THIS ( %s ) : %d' % (self.method.get_name(), self.this)
                self.memory[self.this] = Register(this, self.this)
                for i in xrange(1, self.nbparams):
                    num = self.this + i
                    self.memory[num] = Register(Param('param%s' % i, self.paramsType[i - 1]), num)
                    self.lparams.append(self.memory[num])
        self.ins = []
        self.cur = 0

    def process(self):
        if len(self.basic_blocks) < 1:
            return
        self.blocks = set(self.basic_blocks)
        start = self.basic_blocks[0]
        self._process_blocks(start)
        return self.debug()

    def _process_blocks(self, start):
        self.blocks.remove(start)
        lins = start.get_ins()
        cur = 0
        while self._process_next_ins(cur, lins):
            cur += 1
            Util.log('========================', 'debug')
        Util.log('\n', 'debug')
        if len(start.childs) < 1:
            return
        savedmemory = copy.deepcopy(self.memory)

        Util.log('Memory saved :', 'debug')
        for i in savedmemory.values():
            Util.log(str(i), 'debug')

        if len(start.childs) > 1:
            for child in start.childs:
                if child[2] in self.blocks:
                    self.memory = copy.deepcopy(savedmemory)

                    Util.log('Memory Restored :', 'debug')
                    for i in self.memory.values():
                        Util.log(str(i), 'debug')

                    self._process_blocks(child[2])
        else:
            child = start.childs[0][2]
            if child in self.blocks:
                self.memory = copy.deepcopy(savedmemory)

                Util.log('Memory Restored :', 'debug')
                for i in self.memory.values():
                    Util.log(str(i), 'debug')

                self._process_blocks(child)

    def _process_next_ins(self, cur, lins):
        if cur < len(lins):
            heap = self.memory.get('heap')
            ins = lins[cur]
            Util.log('Name : %s, Operands : %s' % (ins.get_name(), ins.get_operands()), 'debug')
            newIns = Instruction.INSTRUCTION_SET.get(ins.get_name().lower())
            if newIns is None:
                Util.log('Unknown instruction : %s.' % ins.get_name().lower(), 'error')
                return False
            newIns = newIns(ins.get_operands())
            newIns.set_dest_dump(self.ins)
            newIns.emulate(self.memory)
            regnum = newIns.get_reg()
            if regnum is not None:
                register = self.memory.get(regnum)
                if register is None:
                    self.memory[newIns.get_reg()] = Register(newIns, regnum)
                else:
                    register.modify(newIns)
            Util.log('---> newIns : %s, register : %s.' % (ins.get_name(), regnum), 'debug')
            heapaft = self.memory.get('heap')
            if heap is not None and heapaft is not None:
                Util.log('Append : %s' % heap.get_value(), 'debug')
                self.ins.append(heap.get_value())
                if heap == heapaft:
                    Util.log('HEAP = %s' % heap, 'debug')
                    Util.log('HEAPAFT = %s' % heapaft, 'debug')
                    self.memory['heap'] = None
            return True
        return False

    def debug(self, code=None):
        if code is None:
            code = []
        Util.log('Dump of method :', 'debug')
        for j in self.memory.values():
            Util.log(j, 'debug')
        Util.log('\n', 'debug')
        Util.log('Dump of ins :', 'debug')
        acc = []
        for i in self.access:
            if i == 0x10000:
                self.type = ''
            else:
                acc.append(Util.ACCESS_FLAGS_METHODS.get(i))

        if self.type:
            proto = '%s %s %s(' % (' '.join(acc), self.type, self.name)
        else:
            proto = '%s %s(' % (' '.join(acc), self.name)
        if self.paramsType:
            proto += ', '.join(['%s %s' % (i, j.get_content().get_value()) for (i, j) in zip(
            self.paramsType, self.lparams)])
        proto += ') {'
        Util.log(proto, 'debug')
        code.append(proto)
        for i in self.ins:
            Util.log('%s;' % i, 'debug')
            code.append('    %s;' % i)
        Util.log('}', 'debug')
        code.append('}')
        return '\n'.join(code)

    def __repr__(self):
        return 'Method %s' % self.name


class DvClass():
    def __init__(self, dvclass, bca):
        self.dvclass = dvclass
        self.subclasses = {}
        self.bca = bca
        self.name = dvclass.get_name()[1:-1].split('/')[-1]
        self.package = dvclass.get_name().rsplit('/', 1)[0][1:].replace('/', '.')
        self.code = []
        self.this = This(self)
        lmethods = [(method.get_idx(), DvMethod(bca.get_method(method), self.this))
                    for method in dvclass.get_methods()]
        self.methods = dict(lmethods)
        self.fields = {}
        for field in dvclass.get_fields():
            self.fields[field.get_name()] = field

        Util.log('Class : %s' % self.name, 'log')
        Util.log('Methods added :', 'log')
        for index, meth in self.methods.iteritems():
            Util.log('%s (%s, %s)' % (index, meth.method.get_class_name(),
                                   meth.name), 'log')
        Util.log('\n', 'log')

    def add_subclass(self, innername, dvclass):
        self.subclasses[innername] = dvclass

    def select_method(self, meth):
        for method in self.methods.values():
            if method.name == meth:
                break
        if method.name != meth:
            Util.log('Method %s not found.' % meth, 'error')
            return
        self.code.append(method.process())

    def get_methods(self):
        meths = self.methods
        for cls in self.subclasses.values():
            meths.update(cls.get_methods())
        return meths

    def select_meth(self, nb):
        self.code.append(self.methods[nb].process())

    def show_code(self):
        for ins in self.code:
            Util.log(ins, 'log')

    def process(self):
        for cls in self.subclasses.values():
            cls.process()
        for meth in self.methods:
            self.select_meth(meth)

    def __str__(self):
        return 'Class name : %s.' % self.name

    def __repr__(self):
        if self.subclasses == []:
            return 'Class instance, %s.' % self.name
        return 'Class instance, %s.\n\t-- Subclasses %s' % (self.name, self.subclasses)


class DvMachine():
    def __init__(self, name):
        vm = androguard.AndroguardS(name)
        self.vm = vm.get_vm()
        self.bca = analysis.VMAnalysis(self.vm)
        ldict = [(dvclass.get_name(), DvClass(dvclass, self.bca))
                 for dvclass in self.vm.get_classes()]
        self.classes = dict(ldict)
        Util.merge_inner(self.classes)

    def get_class(self, className):
        for name, cls in self.classes.iteritems():
            if className in name:
                return cls

    def process_class(self, cls):
        if cls is None:
            Util.log('No class to process.', 'error')
            return
        cls.process()

    def process_method(self, cls, meth):
        if cls is None:
            Util.log('No class to process.', 'error')
            return
        cls.select_meth(meth)

    def show_code(self, cls):
        if cls is None:
            Util.log('Class not found.', 'error')
            return
        cls.show_code()

class wrap_stream(object):
    def __init__(self):
        self.val = ''
    def write(self, s):
        self.val += s
    def __str__(self):
        return ''.join(self.val)

if __name__ == '__main__':
    try:
        TEST = open('examples/android/TestsAndroguard/bin/classes.dex')
    except IOError:
        TEST = open('../examples/android/TestsAndroguard/bin/classes.dex')
    TEST.close()

    Util.DEBUG_LEVEL = 'debug'

    MACHINE = DvMachine(TEST.name)

    from pprint import pprint
    temp = wrap_stream()
    Util.log('===========================', 'log')
    Util.log('Classes :', 'log')
    pprint(MACHINE.classes, temp)
    Util.log(temp, 'log')
    Util.log('===========================', 'log')

    CLS = raw_input('Choose a class: ')
    if CLS == '*':
        for CLS in MACHINE.classes:
            Util.log('CLS : %s' % CLS, 'log')
            cls = MACHINE.get_class(CLS)
            if cls is None:
                Util.log('%s not found.' % CLS, 'error')
            else:
                MACHINE.process_class(cls)
        Util.log('\n\nDump of code:', 'log')
        Util.log('===========================', 'log')
        for CLS in MACHINE.classes:
            MACHINE.show_code(MACHINE.get_class(CLS))
            Util.log('===========================', 'log')
    else:
        CLS = MACHINE.get_class(CLS)
        if CLS is None:
            Util.log('%s not found.' % CLS, 'error')
        else:
            Util.log('======================', 'log')
            temp = wrap_stream()
            pprint(CLS.get_methods(), temp)
            Util.log(temp, 'log')
            Util.log('======================', 'log')
            METH = raw_input('Method: ')
            if METH == '*':
                Util.log('CLASS = %s' % CLS, 'log')
                MACHINE.process_class(CLS)
            else:
                MACHINE.process_method(CLS, int(METH))
            Util.log('\n\nDump of code:', 'log')
            Util.log('===========================', 'log')
            MACHINE.show_code(CLS)

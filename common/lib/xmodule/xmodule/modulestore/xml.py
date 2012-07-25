import logging
from fs.osfs import OSFS
from importlib import import_module
from lxml import etree
from path import path
from xmodule.x_module import XModuleDescriptor, XMLParsingSystem
from xmodule.mako_module import MakoDescriptorSystem
from cStringIO import StringIO
import os
import re

from . import ModuleStore, Location
from .exceptions import ItemNotFoundError

etree.set_default_parser(etree.XMLParser(dtd_validation=False, load_dtd=False,
                                         remove_comments=True, remove_blank_text=True))

log = logging.getLogger('mitx.' + __name__)


# TODO (cpennington): Remove this once all fall 2012 courses have been imported into the cms from xml
def clean_out_mako_templating(xml_string):
    xml_string = xml_string.replace('%include', 'include')
    xml_string = re.sub("(?m)^\s*%.*$", '', xml_string)
    return xml_string


class XMLModuleStore(ModuleStore):
    """
    An XML backed ModuleStore
    """
    def __init__(self, data_dir, default_class=None, eager=False, course_dirs=None):
        """
        Initialize an XMLModuleStore from data_dir

        data_dir: path to data directory containing the course directories
        default_class: dot-separated string defining the default descriptor class to use if non is specified in entry_points
        eager: If true, load the modules children immediately to force the entire course tree to be parsed
        course_dirs: If specified, the list of course_dirs to load. Otherwise, load
            all course dirs
        """

        self.eager = eager
        self.data_dir = path(data_dir)
        self.modules = {}  # location -> XModuleDescriptor
        self.courses = {}  # course_dir -> XModuleDescriptor for the course

        if default_class is None:
            self.default_class = None
        else:
            module_path, _, class_name = default_class.rpartition('.')
            log.debug('module_path = %s' % module_path)
            class_ = getattr(import_module(module_path), class_name)
            self.default_class = class_

        log.debug('XMLModuleStore: eager=%s, data_dir = %s' % (eager, self.data_dir))
        log.debug('default_class = %s' % self.default_class)

        for course_dir in os.listdir(self.data_dir):
            if course_dirs is not None and course_dir not in course_dirs:
                continue

            if not os.path.exists(self.data_dir / course_dir / "course.xml"):
                continue

            try:
                course_descriptor = self.load_course(course_dir)
                self.courses[course_dir] = course_descriptor
            except:
                log.exception("Failed to load course %s" % course_dir)

    def load_course(self, course_dir):
        """
        Load a course into this module store
        course_path: Course directory name
        """

        with open(self.data_dir / course_dir / "course.xml") as course_file:

            # TODO (cpennington): Remove this once all fall 2012 courses have been imported
            # into the cms from xml
            course_file = StringIO(clean_out_mako_templating(course_file.read()))

            course_data = etree.parse(course_file).getroot()
            org = course_data.get('org')

            if org is None:
                log.error(
                    "No 'org' attribute set for course in {dir}. Using default 'edx'".format(
                        dir=course_dir))
                org = 'edx'

            course = course_data.get('course')

            if course is None:
                log.error(
                    "No 'course' attribute set for course in {dir}. Using default '{default}'".format(
                    dir=course_dir,
                    default=course_dir
                ))
                course = course_dir

            class ImportSystem(XMLParsingSystem, MakoDescriptorSystem):
                def __init__(self, xmlstore):
                    """
                    xmlstore: the XMLModuleStore to store the loaded modules in
                    """
                    self.unnamed_modules = 0
                    self.used_slugs = set()

                    def process_xml(xml):
                        try:
                            # TODO (cpennington): Remove this once all fall 2012 courses
                            # have been imported into the cms from xml
                            xml = clean_out_mako_templating(xml)
                            xml_data = etree.fromstring(xml)
                        except:
                            log.exception("Unable to parse xml: {xml}".format(xml=xml))
                            raise
                        if xml_data.get('slug') is None:
                            if xml_data.get('name'):
                                slug = Location.clean(xml_data.get('name'))
                            else:
                                self.unnamed_modules += 1
                                slug = '{tag}_{count}'.format(tag=xml_data.tag,
                                                              count=self.unnamed_modules)

                            if slug in self.used_slugs:
                                self.unnamed_modules += 1
                                slug = '{slug}_{count}'.format(slug=slug,
                                                               count=self.unnamed_modules)

                            self.used_slugs.add(slug)
                            # log.debug('-> slug=%s' % slug)
                            xml_data.set('slug', slug)

                        module = XModuleDescriptor.load_from_xml(
                            etree.tostring(xml_data), self, org,
                            course, xmlstore.default_class)
                        log.debug('==> importing module location %s' % repr(module.location))
                        module.metadata['data_dir'] = course_dir

                        xmlstore.modules[module.location] = module

                        if xmlstore.eager:
                            module.get_children()
                        return module

                    system_kwargs = dict(
                        render_template=lambda: '',
                        load_item=xmlstore.get_item,
                        resources_fs=OSFS(xmlstore.data_dir / course_dir),
                        process_xml=process_xml
                    )
                    MakoDescriptorSystem.__init__(self, **system_kwargs)
                    XMLParsingSystem.__init__(self, **system_kwargs)
                    

            course_descriptor = ImportSystem(self).process_xml(etree.tostring(course_data))
            log.debug('========> Done with course import')
            return course_descriptor

    def get_item(self, location, depth=0):
        """
        Returns an XModuleDescriptor instance for the item at location.
        If location.revision is None, returns the most item with the most
        recent revision

        If any segment of the location is None except revision, raises
            xmodule.modulestore.exceptions.InsufficientSpecificationError
        If no object is found at that location, raises xmodule.modulestore.exceptions.ItemNotFoundError

        location: Something that can be passed to Location
        """
        location = Location(location)
        try:
            return self.modules[location]
        except KeyError:
            raise ItemNotFoundError(location)

    def get_courses(self, depth=0):
        """
        Returns a list of course descriptors
        """
        return self.courses.values()

    def create_item(self, location):
        raise NotImplementedError("XMLModuleStores are read-only")

    def update_item(self, location, data):
        """
        Set the data in the item specified by the location to
        data

        location: Something that can be passed to Location
        data: A nested dictionary of problem data
        """
        raise NotImplementedError("XMLModuleStores are read-only")

    def update_children(self, location, children):
        """
        Set the children for the item specified by the location to
        data

        location: Something that can be passed to Location
        children: A list of child item identifiers
        """
        raise NotImplementedError("XMLModuleStores are read-only")

    def update_metadata(self, location, metadata):
        """
        Set the metadata for the item specified by the location to
        metadata

        location: Something that can be passed to Location
        metadata: A nested dictionary of module metadata
        """
        raise NotImplementedError("XMLModuleStores are read-only")
